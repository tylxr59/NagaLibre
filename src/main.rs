mod config;
mod runtime;
mod session;

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};
use evdev::{Device, EventType};
use std::{
    fs,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::Duration,
};

const PREFIX: &str = "naga-macros";

#[derive(Parser)]
#[command(version, about = "Linux background macros for the Razer Naga V2 Pro")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// List event interfaces, including ones requiring elevated permissions.
    List {
        #[arg(long)]
        json: bool,
    },
    /// JSON-line session for the desktop app; exits when its stdin closes.
    Session,
    /// Show mouse key/button events without changing or grabbing the devices.
    Monitor {
        /// Restrict to these event paths (repeat for multiple interfaces).
        #[arg(short, long)]
        device: Vec<PathBuf>,
    },
    /// Validate a macro file without accessing hardware.
    Check { config: PathBuf },
    /// Grab input, suppress mapped buttons, and play macros until Ctrl+C.
    Run {
        config: PathBuf,
        /// Restrict to these event paths (repeat for multiple interfaces).
        #[arg(short, long)]
        device: Vec<PathBuf>,
    },
}

#[derive(Debug, serde::Serialize)]
struct Candidate {
    path: PathBuf,
    name: String,
    vendor: u16,
    product: u16,
}

impl Candidate {
    fn is_naga(&self) -> bool {
        self.vendor == 0x1532
            && (matches!(self.product, 0x00a7 | 0x00a8)
                || self.name.to_ascii_lowercase().contains("naga v2 pro"))
    }
}

fn candidates() -> Result<Vec<Candidate>> {
    let mut result = Vec::new();
    for entry in fs::read_dir("/sys/class/input").context("Reading Linux input devices")? {
        let entry = entry?;
        let name = entry.file_name();
        if !name.to_string_lossy().starts_with("event") {
            continue;
        }
        let base = entry.path().join("device");
        let read = |p: &str| {
            fs::read_to_string(base.join(p))
                .unwrap_or_default()
                .trim()
                .to_owned()
        };
        result.push(Candidate {
            path: PathBuf::from("/dev/input").join(name),
            name: read("name"),
            vendor: u16::from_str_radix(&read("id/vendor"), 16).unwrap_or(0),
            product: u16::from_str_radix(&read("id/product"), 16).unwrap_or(0),
        });
    }
    result.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(result)
}

fn open_devices(paths: Vec<PathBuf>) -> Result<Vec<(PathBuf, Device)>> {
    let paths = if paths.is_empty() {
        candidates()?
            .into_iter()
            .filter(Candidate::is_naga)
            .map(|c| c.path)
            .collect()
    } else {
        paths
    };
    if paths.is_empty() {
        bail!(
            "No Naga V2 Pro input devices found. Connect the mouse and run `naga-macros list`. You can select an interface with --device /dev/input/eventN."
        );
    }
    let mut seen = std::collections::BTreeSet::new();
    let mut devices = Vec::new();
    for path in paths {
        let canonical =
            fs::canonicalize(&path).with_context(|| format!("Resolving {}", path.display()))?;
        if !seen.insert(canonical) {
            continue;
        }
        let dev = Device::open(&path).with_context(|| format!("Opening {}. Try sudo for testing, or grant access only to the mouse input interfaces.", path.display()))?;
        if dev.name().unwrap_or_default().starts_with(PREFIX) {
            bail!(
                "Refusing to read our own virtual input device {}",
                path.display()
            );
        }
        dev.set_nonblocking(true)?;
        eprintln!(
            "Selected {}: {}",
            path.display(),
            dev.name().unwrap_or("unknown")
        );
        devices.push((path, dev));
    }
    Ok(devices)
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let running = Arc::new(AtomicBool::new(true));
    let signal = running.clone();
    ctrlc::set_handler(move || signal.store(false, Ordering::Relaxed))?;
    match cli.command {
        Command::Session => session::run(running)?,
        Command::List { json } => {
            let devices = candidates()?;
            if json {
                println!(
                    "{}",
                    serde_json::to_string(
                        &devices
                            .into_iter()
                            .filter(Candidate::is_naga)
                            .collect::<Vec<_>>()
                    )?
                );
                return Ok(());
            }
            let found = devices.iter().any(Candidate::is_naga);
            for dev in devices {
                println!(
                    "{} {:04x}:{:04x} {}{}",
                    dev.path.display(),
                    dev.vendor,
                    dev.product,
                    dev.name,
                    if dev.is_naga() { " [Naga V2 Pro]" } else { "" }
                );
            }
            if !found {
                eprintln!("No Naga V2 Pro detected on this machine.");
            }
        }
        Command::Check { config } => {
            let bindings = config::load(&config)?;
            for (key, m) in &bindings {
                if let Some(target) = m.remap {
                    println!("{key:?}: held key {target:?}");
                    continue;
                }
                println!(
                    "{key:?}: {} key events, {}ms",
                    m.actions.len(),
                    m.duration_ms
                );
            }
            println!("Valid: {} bindings", bindings.len());
        }
        Command::Monitor { device } => {
            let mut devices = open_devices(device)?;
            eprintln!(
                "Press side buttons one at a time. 1=press, 0=release, 2=repeat. Ctrl+C stops.\nDevices are not grabbed; buttons still reach applications."
            );
            while running.load(Ordering::Relaxed) {
                for (path, dev) in &mut devices {
                    match dev.fetch_events() {
                        Ok(events) => {
                            for event in events {
                                if event.event_type() == EventType::KEY {
                                    println!(
                                        "{} {:?} {}",
                                        path.display(),
                                        evdev::KeyCode(event.code()),
                                        event.value()
                                    );
                                }
                            }
                        }
                        Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                        Err(e) => {
                            return Err(e).with_context(|| {
                                format!(
                                    "Reading {}; reconnect the mouse and restart monitor",
                                    path.display()
                                )
                            });
                        }
                    }
                }
                thread::sleep(Duration::from_millis(2));
            }
        }
        Command::Run { config, device } => {
            let bindings = config::load(&config)?;
            runtime::run(open_devices(device)?, bindings, running)?;
        }
    }
    Ok(())
}
