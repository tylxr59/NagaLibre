mod config;
mod devices;
mod diagnostics;
mod faceplate;
mod onboard;
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
    /// Read slot capacity, initialized IDs and active slot without reading bindings or serials.
    OnboardSlots,
    /// Collect passive Razer diagnostics, including unknown devices; no vendor requests.
    Diagnose,
    /// List model definitions and verified/experimental capabilities.
    Models,
    /// Read the attached hardware-module ID without changing mouse settings.
    Faceplate {
        /// Print one reading per second until Ctrl+C.
        #[arg(long)]
        watch: bool,
    },
    /// Read raw profile-query payloads for troubleshooting, without changing settings.
    OnboardProbe {
        /// Also read raw primary and twelve side-button payloads from this slot.
        #[arg(long, value_parser = clap::value_parser!(u8).range(1..=5))]
        slot: Option<u8>,
    },
    /// Read onboard slots and twelve side-button records without changing settings.
    OnboardRead {
        #[arg(long)]
        slot: Option<u8>,
    },
    /// List event interfaces, including ones requiring elevated permissions.
    List {
        #[arg(long)]
        json: bool,
        /// Include unknown Razer products and unsupported connections in JSON output.
        #[arg(long)]
        all_razer: bool,
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
    physical_id: String,
    model: Option<&'static devices::Model>,
}

impl Candidate {
    fn is_supported(&self) -> bool {
        self.model.is_some()
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
        let vendor = u16::from_str_radix(&read("id/vendor"), 16).unwrap_or(0);
        let product = u16::from_str_radix(&read("id/product"), 16).unwrap_or(0);
        let mut physical = fs::canonicalize(&base)?;
        // Group composite event nodes by their USB device, not event number or
        // model ID. Two mice of the same model must remain distinct.
        let physical_id = loop {
            if physical.join("idVendor").exists() || !physical.pop() {
                break physical.display().to_string();
            }
        };
        result.push(Candidate {
            path: PathBuf::from("/dev/input").join(name),
            name: read("name"),
            vendor,
            product,
            physical_id,
            model: if read("id/bustype") == "0003" {
                devices::lookup(vendor, product)
            } else {
                None
            },
        });
    }
    result.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(result)
}

fn selected_device() -> Result<Vec<Candidate>> {
    select_candidates(candidates()?)
}

fn select_candidates(candidates: Vec<Candidate>) -> Result<Vec<Candidate>> {
    let devices: Vec<_> = candidates
        .into_iter()
        .filter(Candidate::is_supported)
        .collect();
    let physical: std::collections::BTreeSet<_> = devices.iter().map(|d| &d.physical_id).collect();
    anyhow::ensure!(
        !physical.is_empty(),
        "No supported Razer mouse found. Connect one mouse by USB or its supported receiver."
    );
    anyhow::ensure!(
        physical.len() == 1,
        "Multiple supported mice connected. Connect one mouse for automatic selection, or use explicit --device paths in the CLI."
    );
    Ok(devices)
}

fn open_devices(paths: Vec<PathBuf>) -> Result<Vec<(PathBuf, Device)>> {
    let paths = if paths.is_empty() {
        selected_device()?
            .into_iter()
            .filter(Candidate::is_supported)
            .map(|c| c.path)
            .collect()
    } else {
        paths
    };
    if paths.is_empty() {
        bail!(
            "No supported Razer mouse input devices found. Connect the mouse and run `naga-macros list`. You can select an interface with --device /dev/input/eventN."
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
        Command::OnboardSlots => println!(
            "{}",
            serde_json::to_string_pretty(&onboard::hidraw::connect()?.slot_inventory()?)?
        ),
        Command::Diagnose => println!(
            "{}",
            serde_json::to_string_pretty(&diagnostics::collect(std::path::Path::new("/")))?
        ),
        Command::Models => println!("{}", serde_json::to_string_pretty(devices::models())?),
        Command::Faceplate { watch } => {
            let mut mouse = onboard::hidraw::connect()?;
            loop {
                let plate = faceplate::read(&mut mouse)?;
                session::emit(
                    serde_json::json!({"type":"faceplate", "module_id":plate.module_id, "buttons":plate.buttons}),
                );
                if !watch || !running.load(Ordering::Relaxed) {
                    break;
                }
                thread::sleep(Duration::from_secs(1));
            }
        }
        Command::OnboardProbe { slot } => {
            use onboard::Transport;
            let mut mouse = onboard::hidraw::connect()?;
            let mut reads = Vec::new();
            let mut queries: Vec<_> = [
                ("serial", 0, 0x82, 22),
                ("mode", 0, 0x84, 2),
                ("inventory", 5, 0x81, 6),
                ("active", 5, 0x84, 6),
            ]
            .into_iter()
            .map(|(name, class, command, size)| (name.to_owned(), class, command, vec![0; size], 0))
            .collect();
            if let Some(slot) = slot {
                for id in [1, 2].into_iter().chain(0x40..=0x4b) {
                    let mut payload = vec![0; 10];
                    payload[0] = slot;
                    payload[1] = id;
                    queries.push((format!("slot_{slot}_button_{id:02x}"), 2, 0x8c, payload, 3));
                }
            }
            for (name, class, command, payload, echo) in queries {
                let result = mouse.transport.exchange(class, command, &payload, echo);
                reads.push(match result {
                    Ok(bytes) => serde_json::json!({"query":name,"length":bytes.len(),"payload":bytes,"hex":bytes.iter().map(|b|format!("{b:02x}")).collect::<Vec<_>>().join(" ")}),
                    Err(e) => serde_json::json!({"query":name,"error":format!("{e:#}")}),
                });
            }
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &serde_json::json!({"version":env!("CARGO_PKG_VERSION"),"device":mouse.transport.identity(),"reads":reads})
                )?
            );
        }
        Command::OnboardRead { slot } => {
            let snapshot = onboard::hidraw::connect()?.read(slot)?;
            println!("{}", serde_json::to_string_pretty(&snapshot)?);
        }
        Command::Session => session::run(running)?,
        Command::List { json, all_razer } => {
            let devices = candidates()?;
            if json {
                println!(
                    "{}",
                    serde_json::to_string(
                        &devices
                            .into_iter()
                            .filter(|d| d.is_supported() || (all_razer && d.vendor == 0x1532))
                            .collect::<Vec<_>>()
                    )?
                );
                return Ok(());
            }
            let found = devices.iter().any(Candidate::is_supported);
            for dev in devices {
                println!(
                    "{} {:04x}:{:04x} {}{}",
                    dev.path.display(),
                    dev.vendor,
                    dev.product,
                    dev.name,
                    if dev.is_supported() {
                        " [supported model]"
                    } else {
                        ""
                    }
                );
            }
            if !found {
                eprintln!("No supported Razer mouse detected on this machine.");
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

#[cfg(test)]
mod device_selection_tests {
    use super::*;

    fn candidate(product: u16, physical_id: &str) -> Candidate {
        Candidate {
            path: PathBuf::from("/dev/input/event-test"),
            name: "test".into(),
            vendor: 0x1532,
            product,
            physical_id: physical_id.into(),
            model: devices::lookup(0x1532, product),
        }
    }

    #[test]
    fn composite_interfaces_are_one_mouse_but_multiple_units_are_rejected() {
        assert_eq!(
            select_candidates(vec![candidate(0xa7, "usb-a"), candidate(0xa7, "usb-a")])
                .unwrap()
                .len(),
            2
        );
        assert!(
            select_candidates(vec![candidate(0xa7, "usb-a"), candidate(0xa7, "usb-b")]).is_err()
        );
        assert!(
            select_candidates(vec![candidate(0xa7, "usb-a"), candidate(0x67, "usb-b")]).is_err()
        );
        assert!(select_candidates(vec![candidate(0xffff, "unknown")]).is_err());
    }
}
