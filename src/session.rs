//! The GUI stays unprivileged; the input session receives only data over stdin.
//! EOF is a lifecycle boundary, including when the GUI is killed or crashes.
use crate::{config, onboard, runtime};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    io::{self, BufRead, Write},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread,
    time::Duration,
};

pub fn emit(value: Value) {
    let mut out = io::stdout().lock();
    let _ = writeln!(out, "{value}");
    let _ = out.flush();
}

#[derive(Deserialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    OnboardRestore { backup: onboard::Snapshot },
    OnboardRead { slot: Option<u8> },
    OnboardPrepare { buttons: Vec<onboard::Button> },
    OnboardCommit { token: String },
    Monitor,
    Apply { config: String },
    Shutdown,
}

struct Worker {
    running: Arc<AtomicBool>,
    thread: thread::JoinHandle<()>,
}

impl Worker {
    fn stop(self) {
        self.running.store(false, Ordering::Relaxed);
        let _ = self.thread.join();
    }
}

fn worker(bindings: Option<config::Bindings>) -> Worker {
    let running = Arc::new(AtomicBool::new(true));
    let signal = running.clone();
    let thread = thread::spawn(move || {
        let result = (|| -> Result<()> {
            let mut devices = crate::open_devices(Vec::new())?;
            emit(
                json!({"type":"devices", "devices": devices.iter().map(|(path, d)| json!({"path":path,"name":d.name()})).collect::<Vec<_>>()}),
            );
            if let Some(bindings) = bindings.filter(|b| !b.is_empty()) {
                runtime::run_session(devices, bindings, signal)
            } else {
                emit(json!({"type":"state", "state":"monitoring"}));
                while signal.load(Ordering::Relaxed) {
                    for (path, dev) in &mut devices {
                        match dev.fetch_events() {
                            Ok(events) => {
                                for event in events {
                                    if event.event_type() == evdev::EventType::KEY {
                                        emit(
                                            json!({"type":"input", "path":path,"key":format!("{:?}",evdev::KeyCode(event.code())),"value":event.value()}),
                                        );
                                    }
                                }
                            }
                            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
                            Err(e) => {
                                return Err(e).with_context(|| {
                                    format!(
                                        "Reading {}; reconnect and click Connect",
                                        path.display()
                                    )
                                });
                            }
                        }
                    }
                    thread::sleep(Duration::from_millis(2));
                }
                Ok(())
            }
        })();
        if let Err(e) = result {
            emit(json!({"type":"error","message":format!("{e:#}")}));
        }
        emit(json!({"type":"state","state":"idle"}));
    });
    Worker { running, thread }
}

pub fn run(running: Arc<AtomicBool>) -> Result<()> {
    let (tx, rx) = mpsc::sync_channel(8);
    thread::spawn(move || {
        let mut reader = io::stdin().lock();
        loop {
            let mut line = String::new();
            // Bound a command before allocating an arbitrarily long input line.
            let result = io::Read::take(&mut reader, 1_048_577).read_line(&mut line);
            match result {
                Ok(0) | Err(_) => break,
                Ok(_) if line.len() > 1_048_576 => {
                    let _ = tx.send(Err("Command exceeds 1 MiB".to_owned()));
                    break;
                }
                Ok(_) => {
                    if tx
                        .send(serde_json::from_str::<Command>(&line).map_err(|e| e.to_string()))
                        .is_err()
                    {
                        break;
                    }
                }
            }
        }
        // Dropping tx makes recv detect EOF, even when a worker is active.
    });
    emit(json!({"type":"hello","protocol":2,"version":env!("CARGO_PKG_VERSION")}));
    let mut active: Option<Worker> = None;
    let mut hardware: Option<onboard::Mouse<onboard::hidraw::Hidraw>> = None;
    let mut snapshot: Option<onboard::Snapshot> = None;
    let mut prepared: Option<(String, onboard::Prepared)> = None;
    while running.load(Ordering::Relaxed) {
        let command = match rx.recv_timeout(Duration::from_millis(100)) {
            Ok(Ok(command)) => command,
            Ok(Err(message)) => {
                emit(json!({"type":"error","message":message}));
                continue;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        };
        if matches!(
            command,
            Command::OnboardRead { .. }
                | Command::OnboardRestore { .. }
                | Command::OnboardPrepare { .. }
                | Command::OnboardCommit { .. }
        ) {
            if let Some(worker) = active.take() {
                worker.stop();
            }
            let result = (|| -> Result<()> {
                match command {
                    Command::OnboardRestore { backup } => {
                        prepared = None;
                        snapshot = None;
                        if hardware.is_none() {
                            hardware = Some(onboard::hidraw::connect()?);
                        }
                        let plan = hardware.as_mut().unwrap().prepare_restore(backup)?;
                        let token = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)?
                            .as_nanos()
                            .to_string();
                        emit(json!({"type":"onboard_prepared","token":token,"backup":plan.before}));
                        prepared = Some((token, plan));
                    }
                    Command::OnboardRead { slot } => {
                        prepared = None;
                        snapshot = None;
                        hardware = None;
                        let mut mouse = onboard::hidraw::connect()?;
                        let read = mouse.read(slot)?;
                        emit(json!({"type":"onboard_snapshot","snapshot":read}));
                        snapshot = Some(read);
                        hardware = Some(mouse);
                    }
                    Command::OnboardPrepare { buttons } => {
                        prepared = None;
                        let mouse = hardware
                            .as_mut()
                            .context("Read mouse slots before saving")?;
                        let before = snapshot
                            .as_ref()
                            .context("Read mouse slots before saving")?;
                        let plan = mouse.prepare(before, buttons)?;
                        let token = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)?
                            .as_nanos()
                            .to_string();
                        emit(json!({"type":"onboard_prepared","token":token,"backup":plan.before}));
                        prepared = Some((token, plan));
                    }
                    Command::OnboardCommit { token } => {
                        let (expected, plan) =
                            prepared.take().context("No hardware save is prepared")?;
                        ensure!(
                            expected == token,
                            "Prepared hardware-save token does not match"
                        );
                        let mouse = hardware.as_mut().context("Hardware connection lost")?;
                        snapshot = None;
                        let after = mouse.commit(plan)?;
                        emit(json!({"type":"onboard_saved","snapshot":after}));
                        snapshot = Some(after);
                    }
                    _ => unreachable!(),
                }
                Ok(())
            })();
            if let Err(e) = result {
                prepared = None;
                emit(json!({"type":"error","message":format!("{e:#}")}));
            }
            continue;
        }
        let bindings = match command {
            Command::Shutdown => break,
            Command::Monitor => None,
            Command::Apply { config: text } => match config::parse(&text) {
                Ok(bindings) => Some(bindings),
                Err(e) => {
                    emit(json!({"type":"error","message":format!("{e:#}")}));
                    continue;
                }
            },
            _ => unreachable!(),
        };
        hardware = None;
        snapshot = None;
        prepared = None;
        if let Some(worker) = active.take() {
            worker.stop();
        }
        active = Some(worker(bindings));
    }
    if let Some(worker) = active {
        worker.stop();
    }
    Ok(())
}
