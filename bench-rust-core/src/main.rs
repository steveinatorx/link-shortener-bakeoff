use clap::Parser;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use std::thread;

#[derive(Parser)]
#[command(name = "bench-rust-core")]
#[command(about = "Rust core benchmark for link shortener")]
struct Args {
    #[arg(long, default_value = "data/initial.tsv")]
    initial: String,
    
    #[arg(long, default_value = "data/ops.txt")]
    ops: String,
    
    #[arg(long, default_value = "1")]
    threads: usize,
    
    #[arg(long, default_value = "128")]
    shards: usize,
    
    #[arg(long = "warmup_s", default_value = "2.0")]
    warmup_s: f64,
    
    #[arg(long = "duration_s", default_value = "10.0")]
    duration_s: f64,
    
    #[arg(long, default_value = "results.json")]
    out: String,
}

#[derive(Debug, Clone)]
enum Op {
    Get(String),
    Set(String, String),
}

#[derive(Serialize, Deserialize)]
struct Results {
    meta: Meta,
    config: Config,
    metrics: Metrics,
}

#[derive(Serialize, Deserialize)]
struct Meta {
    timestamp_utc: String,
    os: String,
    arch: String,
    cpu_cores: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    hostname: Option<String>,
}

#[derive(Serialize, Deserialize)]
struct Config {
    language: String,
    language_version: String,
    git_commit: String,
    n_initial: usize,
    ops_file: String,
    read_pct: usize,
    dist: String,
    threads: usize,
    shards: usize,
    seed: usize,
    warmup_s: f64,
    duration_s: f64,
}

#[derive(Serialize, Deserialize)]
struct Metrics {
    ops_total: u64,
    ops_per_sec: f64,
    latency_us_p50: f64,
    latency_us_p95: f64,
    latency_us_p99: f64,
    reads_total: u64,
    reads_per_sec: f64,
    reads_latency_us_p50: f64,
    reads_latency_us_p95: f64,
    reads_latency_us_p99: f64,
    writes_total: u64,
    writes_per_sec: f64,
    writes_latency_us_p50: f64,
    writes_latency_us_p95: f64,
    writes_latency_us_p99: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    rss_bytes: Option<u64>,
}

// FNV-1a 64-bit hash
fn fnv1a64(s: &str) -> u64 {
    const FNV_OFFSET_BASIS: u64 = 14695981039346656037;
    const FNV_PRIME: u64 = 1099511628211;
    
    let mut hash = FNV_OFFSET_BASIS;
    for byte in s.bytes() {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

// Histogram with fine-grained buckets for accurate latency measurement
// Uses 1μs buckets up to 10ms (10,000 buckets), then coarser buckets up to 1s
struct Histogram {
    fine_buckets: Vec<u64>,  // 0-10ms in 1μs steps (10,000 buckets)
    coarse_buckets: Vec<u64>, // 10ms-1s in 1ms steps (990 buckets)
    total: u64,
}

impl Histogram {
    fn new() -> Self {
        Self {
            fine_buckets: vec![0; 10000],  // 0-10ms at 1μs resolution
            coarse_buckets: vec![0; 990], // 10ms-1s at 1ms resolution
            total: 0,
        }
    }
    
    fn record(&mut self, us: u64) {
        if us < 10000 {
            // Fine-grained: 1μs buckets
            self.fine_buckets[us as usize] += 1;
        } else if us < 1000000 {
            // Coarse-grained: 1ms buckets (10ms to 1s)
            let bucket = ((us - 10000) / 1000) as usize;
            if bucket < self.coarse_buckets.len() {
                self.coarse_buckets[bucket] += 1;
            } else {
                // Overflow: put in last bucket
                *self.coarse_buckets.last_mut().unwrap() += 1;
            }
        } else {
            // > 1s: put in last bucket
            *self.coarse_buckets.last_mut().unwrap() += 1;
        }
        self.total += 1;
    }
    
    fn merge(&mut self, other: &Self) {
        for i in 0..self.fine_buckets.len() {
            self.fine_buckets[i] += other.fine_buckets[i];
        }
        for i in 0..self.coarse_buckets.len() {
            self.coarse_buckets[i] += other.coarse_buckets[i];
        }
        self.total += other.total;
    }
    
    fn percentile(&self, p: f64) -> f64 {
        if self.total == 0 {
            return 0.0;
        }
        let target = (self.total as f64 * p / 100.0).ceil() as u64;
        let mut count = 0u64;
        
        // Check fine-grained buckets first
        for (i, &bucket_count) in self.fine_buckets.iter().enumerate() {
            count += bucket_count;
            if count >= target {
                return i as f64; // Return exact microsecond value
            }
        }
        
        // Check coarse-grained buckets
        for (i, &bucket_count) in self.coarse_buckets.iter().enumerate() {
            count += bucket_count;
            if count >= target {
                // Return midpoint of 1ms bucket
                return (10000 + i * 1000 + 500) as f64;
            }
        }
        
        // Fallback: return max (1s)
        1000000.0
    }
}

type ShardedMap = Vec<Arc<std::sync::RwLock<HashMap<String, String>>>>;

fn load_initial(path: &str, shards: usize) -> ShardedMap {
    let file = File::open(path).expect("Failed to open initial.tsv");
    let reader = BufReader::new(file);
    
    let maps: Vec<Arc<std::sync::RwLock<HashMap<String, String>>>> = 
        (0..shards).map(|_| Arc::new(std::sync::RwLock::new(HashMap::new()))).collect();
    
    for line in reader.lines() {
        let line = line.expect("Failed to read line");
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() >= 2 {
            let code = parts[0].to_string();
            let url = parts[1].to_string();
            let shard_idx = (fnv1a64(&code) as usize) % shards;
            maps[shard_idx].write().unwrap().insert(code, url);
        }
    }
    
    maps
}

fn load_ops(path: &str) -> Vec<Op> {
    let file = File::open(path).expect("Failed to open ops.txt");
    let reader = BufReader::new(file);
    let mut ops = Vec::new();
    
    for line in reader.lines() {
        let line = line.expect("Failed to read line");
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() {
            continue;
        }
        match parts[0] {
            "G" if parts.len() >= 2 => {
                ops.push(Op::Get(parts[1].to_string()));
            }
            "S" if parts.len() >= 3 => {
                ops.push(Op::Set(parts[1].to_string(), parts[2..].join(" ")));
            }
            _ => {}
        }
    }
    
    ops
}

struct WorkerResults {
    read_hist: Histogram,
    write_hist: Histogram,
    read_count: u64,
    write_count: u64,
    total_ops: u64,
}

fn worker(
    maps: Arc<ShardedMap>,
    ops: Arc<Vec<Op>>,
    start_idx: usize,
    end_idx: usize,
    warmup_duration: Duration,
    measure_duration: Duration,
    ops_counter: Arc<AtomicU64>,
) -> WorkerResults {
    let mut read_hist = Histogram::new();
    let mut write_hist = Histogram::new();
    let mut local_reads = 0u64;
    let mut local_writes = 0u64;
    let mut local_ops = 0u64;
    
    let warmup_end = Instant::now() + warmup_duration;
    let measure_end = warmup_end + measure_duration;
    
    // Warmup phase
    let mut op_idx = start_idx;
    while Instant::now() < warmup_end {
        let op = &ops[op_idx];
        match op {
            Op::Get(code) => {
                let shard_idx = (fnv1a64(code) as usize) % maps.len();
                let _ = maps[shard_idx].read().unwrap().get(code);
            }
            Op::Set(code, url) => {
                let shard_idx = (fnv1a64(code) as usize) % maps.len();
                maps[shard_idx].write().unwrap().insert(code.clone(), url.clone());
            }
        }
        op_idx += 1;
        if op_idx >= end_idx {
            op_idx = start_idx;
        }
    }
    
    // Measurement phase
    op_idx = start_idx;
    while Instant::now() < measure_end {
        let op = &ops[op_idx];
        let start = Instant::now();
        match op {
            Op::Get(code) => {
                let shard_idx = (fnv1a64(code) as usize) % maps.len();
                let _ = maps[shard_idx].read().unwrap().get(code);
            }
            Op::Set(code, url) => {
                let shard_idx = (fnv1a64(code) as usize) % maps.len();
                maps[shard_idx].write().unwrap().insert(code.clone(), url.clone());
            }
        }
        let elapsed = start.elapsed();
        // Convert nanoseconds to microseconds with rounding
        let ns = elapsed.as_nanos();
        let us = (ns + 500) / 1000; // Round to nearest microsecond
        match op {
            Op::Get(_) => {
                read_hist.record(us as u64);
                local_reads += 1;
            }
            Op::Set(_, _) => {
                write_hist.record(us as u64);
                local_writes += 1;
            }
        }
        local_ops += 1;
        
        op_idx += 1;
        if op_idx >= end_idx {
            op_idx = start_idx;
        }
    }
    
    ops_counter.fetch_add(local_ops, Ordering::Relaxed);
    WorkerResults {
        read_hist,
        write_hist,
        read_count: local_reads,
        write_count: local_writes,
        total_ops: local_ops,
    }
}

fn get_git_commit() -> String {
    std::process::Command::new("git")
        .args(["rev-parse", "--short=12", "HEAD"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

fn get_rustc_version() -> String {
    std::process::Command::new("rustc")
        .args(["--version"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

fn get_rss_bytes() -> Option<u64> {
    // On macOS, we can try to read from /proc/self/status or use sysinfo
    // For simplicity, return None - can be enhanced later
    None
}

fn main() {
    let args = Args::parse();
    
    println!("Loading initial dataset from {}...", args.initial);
    let maps = Arc::new(load_initial(&args.initial, args.shards));
    let n_initial = maps.iter().map(|m| m.read().unwrap().len()).sum();
    println!("Loaded {} entries into {} shards", n_initial, args.shards);
    
    println!("Loading operations from {}...", args.ops);
    let all_ops = Arc::new(load_ops(&args.ops));
    println!("Loaded {} operations", all_ops.len());
    
    let ops_per_thread = all_ops.len() / args.threads;
    let ops_counter = Arc::new(AtomicU64::new(0));
    
    let warmup_duration = Duration::from_secs_f64(args.warmup_s);
    let measure_duration = Duration::from_secs_f64(args.duration_s);
    
    println!("Starting {} threads (warmup: {:?}, measure: {:?})...", 
             args.threads, warmup_duration, measure_duration);
    
    let mut handles = Vec::new();
    for i in 0..args.threads {
        let maps_clone = Arc::clone(&maps);
        let ops_clone = Arc::clone(&all_ops);
        let counter_clone = Arc::clone(&ops_counter);
        let start_idx = i * ops_per_thread;
        let end_idx = if i == args.threads - 1 {
            all_ops.len()
        } else {
            (i + 1) * ops_per_thread
        };
        
        let handle = thread::spawn(move || {
            worker(maps_clone, ops_clone, start_idx, end_idx, 
                   warmup_duration, measure_duration, counter_clone)
        });
        handles.push(handle);
    }
    
    let mut merged_read_hist = Histogram::new();
    let mut merged_write_hist = Histogram::new();
    let mut total_reads = 0u64;
    let mut total_writes = 0u64;
    
    for handle in handles {
        let results = handle.join().unwrap();
        merged_read_hist.merge(&results.read_hist);
        merged_write_hist.merge(&results.write_hist);
        total_reads += results.read_count;
        total_writes += results.write_count;
    }
    
    let ops_total = ops_counter.load(Ordering::Relaxed);
    let ops_per_sec = ops_total as f64 / args.duration_s;
    let reads_per_sec = total_reads as f64 / args.duration_s;
    let writes_per_sec = total_writes as f64 / args.duration_s;
    
    let results = Results {
        meta: Meta {
            timestamp_utc: chrono::Utc::now().to_rfc3339(),
            os: std::env::consts::OS.to_string(),
            arch: std::env::consts::ARCH.to_string(),
            cpu_cores: num_cpus::get(),
            hostname: hostname::get().ok().and_then(|h| h.into_string().ok()),
        },
        config: Config {
            language: "rust".to_string(),
            language_version: get_rustc_version(),
            git_commit: get_git_commit(),
            n_initial,
            ops_file: args.ops.clone(),
            read_pct: 95, // TODO: parse from ops file
            dist: "uniform".to_string(), // TODO: parse from args or ops file
            threads: args.threads,
            shards: args.shards,
            seed: 0, // TODO: should be passed or read from metadata
            warmup_s: args.warmup_s,
            duration_s: args.duration_s,
        },
        metrics: Metrics {
            ops_total,
            ops_per_sec,
            latency_us_p50: {
                let mut combined = Histogram::new();
                combined.merge(&merged_read_hist);
                combined.merge(&merged_write_hist);
                combined.percentile(50.0)
            },
            latency_us_p95: {
                let mut combined = Histogram::new();
                combined.merge(&merged_read_hist);
                combined.merge(&merged_write_hist);
                combined.percentile(95.0)
            },
            latency_us_p99: {
                let mut combined = Histogram::new();
                combined.merge(&merged_read_hist);
                combined.merge(&merged_write_hist);
                combined.percentile(99.0)
            },
            reads_total: total_reads,
            reads_per_sec,
            reads_latency_us_p50: merged_read_hist.percentile(50.0),
            reads_latency_us_p95: merged_read_hist.percentile(95.0),
            reads_latency_us_p99: merged_read_hist.percentile(99.0),
            writes_total: total_writes,
            writes_per_sec,
            writes_latency_us_p50: merged_write_hist.percentile(50.0),
            writes_latency_us_p95: merged_write_hist.percentile(95.0),
            writes_latency_us_p99: merged_write_hist.percentile(99.0),
            rss_bytes: get_rss_bytes(),
        },
    };
    
    // Write JSON
    let json_str = serde_json::to_string_pretty(&results).unwrap();
    let mut file = File::create(&args.out).expect("Failed to create output file");
    file.write_all(json_str.as_bytes()).expect("Failed to write JSON");
    println!("Results written to {}", args.out);
    
    // Append CSV
    let csv_path = "results/results.csv";
    let csv_header = "timestamp_utc,language,language_version,git_commit,os,arch,cpu_cores,n_initial,read_pct,dist,threads,shards,seed,warmup_s,duration_s,ops_total,ops_per_sec,latency_us_p50,latency_us_p95,latency_us_p99,rss_bytes\n";
    let csv_line = format!("{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{:.2},{:.2},{:.2},{:.2},{}\n",
        results.meta.timestamp_utc,
        results.config.language,
        results.config.language_version,
        results.config.git_commit,
        results.meta.os,
        results.meta.arch,
        results.meta.cpu_cores,
        results.config.n_initial,
        results.config.read_pct,
        results.config.dist,
        results.config.threads,
        results.config.shards,
        results.config.seed,
        results.config.warmup_s,
        results.config.duration_s,
        results.metrics.ops_total,
        results.metrics.ops_per_sec,
        results.metrics.latency_us_p50,
        results.metrics.latency_us_p95,
        results.metrics.latency_us_p99,
        results.metrics.rss_bytes.map(|v| v.to_string()).unwrap_or_default(),
    );
    
    std::fs::create_dir_all("results").ok();
    let file_exists = std::path::Path::new(csv_path).exists();
    let mut csv_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(csv_path)
        .expect("Failed to open CSV file");
    if !file_exists {
        csv_file.write_all(csv_header.as_bytes()).ok();
    }
    csv_file.write_all(csv_line.as_bytes()).expect("Failed to write CSV");
    println!("CSV appended to {}", csv_path);
}

