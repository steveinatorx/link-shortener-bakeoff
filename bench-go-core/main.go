package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// FNV-1a 64-bit hash
func fnv1a64(s string) uint64 {
	const fnvOffsetBasis uint64 = 14695981039346656037
	const fnvPrime uint64 = 1099511628211

	hash := fnvOffsetBasis
	for i := 0; i < len(s); i++ {
		hash ^= uint64(s[i])
		hash *= fnvPrime
	}
	return hash
}

type Op struct {
	Type string
	Code string
	URL  string
}

type Shard struct {
	mu sync.RWMutex
	m  map[string]string
}

type ShardedMap struct {
	shards []*Shard
}

func NewShardedMap(numShards int) *ShardedMap {
	shards := make([]*Shard, numShards)
	for i := range shards {
		shards[i] = &Shard{
			m: make(map[string]string),
		}
	}
	return &ShardedMap{shards: shards}
}

func (sm *ShardedMap) Get(code string) (string, bool) {
	shardIdx := int(fnv1a64(code) % uint64(len(sm.shards)))
	sm.shards[shardIdx].mu.RLock()
	defer sm.shards[shardIdx].mu.RUnlock()
	val, ok := sm.shards[shardIdx].m[code]
	return val, ok
}

func (sm *ShardedMap) Set(code, url string) {
	shardIdx := int(fnv1a64(code) % uint64(len(sm.shards)))
	sm.shards[shardIdx].mu.Lock()
	defer sm.shards[shardIdx].mu.Unlock()
	sm.shards[shardIdx].m[code] = url
}

// Histogram with fine-grained buckets for accurate latency measurement
// Uses 1μs buckets up to 10ms (10,000 buckets), then coarser buckets up to 1s
type Histogram struct {
	fineBuckets   []uint64 // 0-10ms in 1μs steps (10,000 buckets)
	coarseBuckets []uint64 // 10ms-1s in 1ms steps (990 buckets)
	total         uint64
	mu            sync.Mutex
}

func NewHistogram() *Histogram {
	return &Histogram{
		fineBuckets:   make([]uint64, 10000), // 0-10ms at 1μs resolution
		coarseBuckets: make([]uint64, 990),   // 10ms-1s at 1ms resolution
	}
}

func (h *Histogram) Record(us uint64) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if us < 10000 {
		// Fine-grained: 1μs buckets
		h.fineBuckets[us]++
	} else if us < 1000000 {
		// Coarse-grained: 1ms buckets (10ms to 1s)
		bucket := int((us - 10000) / 1000)
		if bucket < len(h.coarseBuckets) {
			h.coarseBuckets[bucket]++
		} else {
			// Overflow: put in last bucket
			h.coarseBuckets[len(h.coarseBuckets)-1]++
		}
	} else {
		// > 1s: put in last bucket
		h.coarseBuckets[len(h.coarseBuckets)-1]++
	}
	h.total++
}

func (h *Histogram) Merge(other *Histogram) {
	h.mu.Lock()
	defer h.mu.Unlock()
	other.mu.Lock()
	defer other.mu.Unlock()
	for i := range h.fineBuckets {
		h.fineBuckets[i] += other.fineBuckets[i]
	}
	for i := range h.coarseBuckets {
		h.coarseBuckets[i] += other.coarseBuckets[i]
	}
	h.total += other.total
}

func (h *Histogram) Percentile(p float64) float64 {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.total == 0 {
		return 0.0
	}
	target := uint64(float64(h.total) * p / 100.0)
	var count uint64

	// Check fine-grained buckets first
	for i, bucketCount := range h.fineBuckets {
		count += bucketCount
		if count >= target {
			return float64(i) // Return exact microsecond value
		}
	}

	// Check coarse-grained buckets
	for i, bucketCount := range h.coarseBuckets {
		count += bucketCount
		if count >= target {
			// Return midpoint of 1ms bucket
			return float64(10000 + i*1000 + 500)
		}
	}

	// Fallback: return max (1s)
	return 1000000.0
}

func loadInitial(path string, numShards int) *ShardedMap {
	file, err := os.Open(path)
	if err != nil {
		panic(fmt.Sprintf("Failed to open initial.tsv: %v", err))
	}
	defer file.Close()

	sm := NewShardedMap(numShards)
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		parts := strings.Split(line, "\t")
		if len(parts) >= 2 {
			code := parts[0]
			url := parts[1]
			sm.Set(code, url)
		}
	}
	return sm
}

func loadOps(path string) []Op {
	file, err := os.Open(path)
	if err != nil {
		panic(fmt.Sprintf("Failed to open ops.txt: %v", err))
	}
	defer file.Close()

	var ops []Op
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		parts := strings.Fields(line)
		if len(parts) == 0 {
			continue
		}
		switch parts[0] {
		case "G":
			if len(parts) >= 2 {
				ops = append(ops, Op{Type: "G", Code: parts[1]})
			}
		case "S":
			if len(parts) >= 3 {
				ops = append(ops, Op{Type: "S", Code: parts[1], URL: strings.Join(parts[2:], " ")})
			}
		}
	}
	return ops
}

func worker(
	sm *ShardedMap,
	ops []Op,
	startIdx, endIdx int,
	warmupDuration, measureDuration time.Duration,
	opsCounter *atomic.Uint64,
) *Histogram {
	hist := NewHistogram()
	var localOps uint64

	warmupEnd := time.Now().Add(warmupDuration)
	measureEnd := warmupEnd.Add(measureDuration)

	// Warmup phase
	opIdx := startIdx
	for time.Now().Before(warmupEnd) {
		op := ops[opIdx]
		switch op.Type {
		case "G":
			_, _ = sm.Get(op.Code)
		case "S":
			sm.Set(op.Code, op.URL)
		}
		opIdx++
		if opIdx >= endIdx {
			opIdx = startIdx
		}
	}

	// Measurement phase
	opIdx = startIdx
	for time.Now().Before(measureEnd) {
		op := ops[opIdx]
		start := time.Now()
		switch op.Type {
		case "G":
			_, _ = sm.Get(op.Code)
		case "S":
			sm.Set(op.Code, op.URL)
		}
		elapsed := time.Since(start)
		// Convert nanoseconds to microseconds with rounding
		ns := elapsed.Nanoseconds()
		us := (ns + 500) / 1000 // Round to nearest microsecond
		hist.Record(uint64(us))
		localOps++

		opIdx++
		if opIdx >= endIdx {
			opIdx = startIdx
		}
	}

	opsCounter.Add(localOps)
	return hist
}

func getGitCommit() string {
	cmd := exec.Command("git", "rev-parse", "--short=12", "HEAD")
	output, err := cmd.Output()
	if err == nil && len(output) > 0 {
		return strings.TrimSpace(string(output))
	}
	return "unknown"
}

func getGoVersion() string {
	return runtime.Version()
}

func getRSSBytes() *uint64 {
	// On macOS, RSS is not easily accessible without external tools
	// Return nil for now
	return nil
}


type Results struct {
	Meta    Meta    `json:"meta"`
	Config  Config  `json:"config"`
	Metrics Metrics `json:"metrics"`
}

type Meta struct {
	TimestampUTC string  `json:"timestamp_utc"`
	OS           string  `json:"os"`
	Arch         string  `json:"arch"`
	CPUCores     int     `json:"cpu_cores"`
	Hostname     *string `json:"hostname,omitempty"`
}

type Config struct {
	Language      string  `json:"language"`
	LanguageVersion string `json:"language_version"`
	GitCommit     string  `json:"git_commit"`
	NInitial     int     `json:"n_initial"`
	OpsFile       string  `json:"ops_file"`
	ReadPct       int     `json:"read_pct"`
	Dist          string  `json:"dist"`
	Threads       int     `json:"threads"`
	Shards        int     `json:"shards"`
	Seed          int     `json:"seed"`
	WarmupS       float64 `json:"warmup_s"`
	DurationS     float64 `json:"duration_s"`
}

type Metrics struct {
	OpsTotal     uint64   `json:"ops_total"`
	OpsPerSec    float64  `json:"ops_per_sec"`
	LatencyUsP50 float64  `json:"latency_us_p50"`
	LatencyUsP95 float64  `json:"latency_us_p95"`
	LatencyUsP99 float64  `json:"latency_us_p99"`
	RSSBytes     *uint64  `json:"rss_bytes,omitempty"`
}

func main() {
	var (
		initial    = flag.String("initial", "data/initial.tsv", "Path to initial dataset")
		ops        = flag.String("ops", "data/ops.txt", "Path to operations file")
		threads    = flag.Int("threads", 1, "Number of worker threads")
		shards     = flag.Int("shards", 128, "Number of shards")
		warmupS    = flag.Float64("warmup", 2.0, "Warmup duration in seconds")
		durationS  = flag.Float64("duration", 10.0, "Measurement duration in seconds")
		out        = flag.String("out", "results.json", "Output JSON file")
	)
	flag.Parse()

	fmt.Printf("Loading initial dataset from %s...\n", *initial)
	sm := loadInitial(*initial, *shards)
	nInitial := 0
	for _, shard := range sm.shards {
		shard.mu.RLock()
		nInitial += len(shard.m)
		shard.mu.RUnlock()
	}
	fmt.Printf("Loaded %d entries into %d shards\n", nInitial, *shards)

	fmt.Printf("Loading operations from %s...\n", *ops)
	allOps := loadOps(*ops)
	fmt.Printf("Loaded %d operations\n", len(allOps))

	opsPerThread := len(allOps) / *threads
	opsCounter := &atomic.Uint64{}

	warmupDuration := time.Duration(*warmupS * float64(time.Second))
	measureDuration := time.Duration(*durationS * float64(time.Second))

	fmt.Printf("Starting %d goroutines (warmup: %v, measure: %v)...\n",
		*threads, warmupDuration, measureDuration)

	var wg sync.WaitGroup
	histograms := make([]*Histogram, *threads)
	for i := 0; i < *threads; i++ {
		startIdx := i * opsPerThread
		endIdx := startIdx + opsPerThread
		if i == *threads-1 {
			endIdx = len(allOps)
		}

		wg.Add(1)
		go func(idx, start, end int) {
			defer wg.Done()
			histograms[idx] = worker(sm, allOps, start, end, warmupDuration, measureDuration, opsCounter)
		}(i, startIdx, endIdx)
	}
	wg.Wait()

	mergedHist := NewHistogram()
	for _, h := range histograms {
		mergedHist.Merge(h)
	}

	opsTotal := opsCounter.Load()
	opsPerSec := float64(opsTotal) / *durationS

	hostname, _ := os.Hostname()
	var hostnamePtr *string
	if hostname != "" {
		hostnamePtr = &hostname
	}

	results := Results{
		Meta: Meta{
			TimestampUTC: time.Now().UTC().Format(time.RFC3339),
			OS:           runtime.GOOS,
			Arch:         runtime.GOARCH,
			CPUCores:     runtime.NumCPU(),
			Hostname:     hostnamePtr,
		},
		Config: Config{
			Language:        "go",
			LanguageVersion: getGoVersion(),
			GitCommit:       getGitCommit(),
			NInitial:        nInitial,
			OpsFile:         *ops,
			ReadPct:         95, // TODO: parse from ops
			Dist:             "uniform", // TODO: parse from args
			Threads:          *threads,
			Shards:           *shards,
			Seed:             0, // TODO: should be passed
			WarmupS:          *warmupS,
			DurationS:        *durationS,
		},
		Metrics: Metrics{
			OpsTotal:     opsTotal,
			OpsPerSec:    opsPerSec,
			LatencyUsP50: mergedHist.Percentile(50.0),
			LatencyUsP95: mergedHist.Percentile(95.0),
			LatencyUsP99: mergedHist.Percentile(99.0),
			RSSBytes:     getRSSBytes(),
		},
	}

	// Write JSON
	jsonBytes, err := json.MarshalIndent(results, "", "  ")
	if err != nil {
		panic(fmt.Sprintf("Failed to marshal JSON: %v", err))
	}
	if err := os.WriteFile(*out, jsonBytes, 0644); err != nil {
		panic(fmt.Sprintf("Failed to write JSON: %v", err))
	}
	fmt.Printf("Results written to %s\n", *out)

	// Append CSV
	csvPath := "results/results.csv"
	csvHeader := "timestamp_utc,language,language_version,git_commit,os,arch,cpu_cores,n_initial,read_pct,dist,threads,shards,seed,warmup_s,duration_s,ops_total,ops_per_sec,latency_us_p50,latency_us_p95,latency_us_p99,rss_bytes\n"
	csvLine := fmt.Sprintf("%s,%s,%s,%s,%s,%s,%d,%d,%d,%s,%d,%d,%d,%.2f,%.2f,%d,%.2f,%.2f,%.2f,%.2f,%s\n",
		results.Meta.TimestampUTC,
		results.Config.Language,
		results.Config.LanguageVersion,
		results.Config.GitCommit,
		results.Meta.OS,
		results.Meta.Arch,
		results.Meta.CPUCores,
		results.Config.NInitial,
		results.Config.ReadPct,
		results.Config.Dist,
		results.Config.Threads,
		results.Config.Shards,
		results.Config.Seed,
		results.Config.WarmupS,
		results.Config.DurationS,
		results.Metrics.OpsTotal,
		results.Metrics.OpsPerSec,
		results.Metrics.LatencyUsP50,
		results.Metrics.LatencyUsP95,
		results.Metrics.LatencyUsP99,
		func() string {
			if results.Metrics.RSSBytes != nil {
				return strconv.FormatUint(*results.Metrics.RSSBytes, 10)
			}
			return ""
		}(),
	)

	os.MkdirAll("results", 0755)
	fileExists := false
	if _, err := os.Stat(csvPath); err == nil {
		fileExists = true
	}

	var csvFile *os.File
	var err2 error
	if fileExists {
		csvFile, err2 = os.OpenFile(csvPath, os.O_APPEND|os.O_WRONLY, 0644)
	} else {
		csvFile, err2 = os.Create(csvPath)
		if err2 == nil {
			csvFile.WriteString(csvHeader)
		}
	}
	if err2 != nil {
		panic(fmt.Sprintf("Failed to open CSV: %v", err2))
	}
	defer csvFile.Close()
	csvFile.WriteString(csvLine)
	fmt.Printf("CSV appended to %s\n", csvPath)
}

