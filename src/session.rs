//! The GUI stays unprivileged; the input session receives only data over stdin.
//! EOF is a lifecycle boundary, including when the GUI is killed or crashes.
use crate::{config, faceplate, onboard, runtime};
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
    time::{Duration, Instant},
};

pub fn emit(value: Value) {
    let mut out = io::stdout().lock();
    let _ = writeln!(out, "{value}");
    let _ = out.flush();
}

#[derive(Deserialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    OnboardActivate {
        slot: u8,
    },
    OnboardCreate {
        slot: u8,
    },
    Faceplate,
    OnboardRestore {
        backup: onboard::Snapshot,
    },
    OnboardRead {
        slot: Option<u8>,
    },
    OnboardPrepare {
        buttons: Vec<onboard::Button>,
        #[serde(default)]
        controls: Vec<onboard::Button>,
    },
    OnboardCommit {
        token: String,
    },
    Monitor,
    Apply {
        config: String,
        module_id: Option<u8>,
    },
    Shutdown,
}

enum HardwarePlan {
    Activation(onboard::activation::PreparedActivation),
    Bindings(onboard::Prepared),
    Creation(onboard::creation::PreparedCreation),
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

fn worker(
    bindings: Option<config::Bindings>,
    physical_id: Option<String>,
    model_id: Option<&'static str>,
) -> Worker {
    let running = Arc::new(AtomicBool::new(true));
    let signal = running.clone();
    let thread = thread::spawn(move || {
        let result = (|| -> Result<()> {
            let current = crate::selected_device()?;
            ensure!(
                Some(&current[0].physical_id) == physical_id.as_ref()
                    && current[0].model.map(|m| m.id.as_str()) == model_id,
                "Mouse changed; reconnect before using bindings"
            );
            let mut devices = crate::open_devices(current.into_iter().map(|d| d.path).collect())?;
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

fn read_plate(
    hardware: &mut Option<onboard::Mouse<onboard::hidraw::Hidraw>>,
) -> Result<faceplate::Faceplate> {
    if hardware.is_none() {
        *hardware = Some(onboard::hidraw::connect()?);
    }
    faceplate::read(hardware.as_mut().unwrap())
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
    let selection = crate::selected_device();
    let device = selection.as_ref().ok().and_then(|d| d[0].model);
    let physical_id = selection.as_ref().ok().map(|d| d[0].physical_id.clone());
    emit(
        json!({"type":"hello","protocol":4,"version":env!("CARGO_PKG_VERSION"), "device":device,
        "slot_creation":selection.as_ref().is_ok_and(|d| d[0].product == 0xa7),
        "slot_activation":device.is_some_and(|d| d.onboard),
        "wheel_controls":device.is_some_and(|d| d.onboard),
        "device_error":selection.as_ref().err().map(|e| format!("{e:#}"))}),
    );
    let mut active: Option<Worker> = None;
    let mut hardware: Option<onboard::Mouse<onboard::hidraw::Hidraw>> = None;
    let mut snapshot: Option<onboard::Snapshot> = None;
    let mut prepared: Option<(String, HardwarePlan)> = None;
    let mut watching_plate = false;
    let mut next_plate = Instant::now();
    let mut last_plate = None;
    while running.load(Ordering::Relaxed) {
        if watching_plate && Instant::now() >= next_plate {
            let event = match read_plate(&mut hardware) {
                Ok(plate) => {
                    json!({"type":"faceplate", "module_id":plate.module_id, "buttons":plate.buttons})
                }
                Err(e) => {
                    hardware = None;
                    json!({"type":"faceplate", "module_id":null, "buttons":null, "message":format!("{e:#}")})
                }
            };
            if last_plate.as_ref() != Some(&event) {
                // Stop and release software output before telling the UI to switch drafts.
                if let Some(worker) = active.take() {
                    worker.stop();
                }
                prepared = None;
                snapshot = None;
                emit(event.clone());
                last_plate = Some(event);
            }
            next_plate = Instant::now() + Duration::from_secs(1);
        }
        let command = match rx.recv_timeout(Duration::from_millis(100)) {
            Ok(Ok(command)) => command,
            Ok(Err(message)) => {
                emit(json!({"type":"error","message":message}));
                continue;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        };
        if matches!(command, Command::Faceplate) {
            if !device.is_some_and(|d| d.faceplate) {
                emit(
                    json!({"type":"faceplate", "module_id":null, "buttons":null, "message":"Automatic faceplate queries are not enabled for this model"}),
                );
                continue;
            }
            watching_plate = true;
            next_plate = Instant::now();
            continue;
        }
        if matches!(
            command,
            Command::OnboardRead { .. }
                | Command::OnboardActivate { .. }
                | Command::OnboardCreate { .. }
                | Command::OnboardRestore { .. }
                | Command::OnboardPrepare { .. }
                | Command::OnboardCommit { .. }
        ) {
            if !device.is_some_and(|d| d.onboard) {
                emit(
                    json!({"type":"error", "message":"Onboard access is not enabled for this model. Use Software mode and Learn input."}),
                );
                continue;
            }
            if let Some(worker) = active.take() {
                worker.stop();
            }
            let result = (|| -> Result<()> {
                match command {
                    Command::OnboardActivate { slot } => {
                        prepared = None;
                        ensure!(
                            read_plate(&mut hardware)?.buttons == Some(12),
                            "Attach the 12-button plate before activating a slot"
                        );
                        let before = snapshot
                            .as_ref()
                            .context("Read mouse slots before activation")?;
                        let plan = hardware
                            .as_mut()
                            .context("Hardware connection lost")?
                            .prepare_activation(before, slot)?;
                        let token = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)?
                            .as_nanos()
                            .to_string();
                        emit(
                            json!({"type":"onboard_activation_prepared", "token":token, "backup":plan.before, "previous":plan.previous}),
                        );
                        prepared = Some((token, HardwarePlan::Activation(plan)));
                    }
                    Command::OnboardCreate { slot } => {
                        prepared = None;
                        ensure!(
                            read_plate(&mut hardware)?.buttons == Some(12),
                            "Attach the 12-button plate before creating a slot"
                        );
                        let before = snapshot
                            .as_ref()
                            .context("Read mouse slots before creating a slot")?;
                        let plan = hardware
                            .as_mut()
                            .context("Hardware connection lost")?
                            .prepare_creation(before, slot)?;
                        let token = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)?
                            .as_nanos()
                            .to_string();
                        emit(
                            json!({"type":"onboard_creation_prepared", "token":token, "backup":plan.backup}),
                        );
                        prepared = Some((token, HardwarePlan::Creation(plan)));
                    }
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
                        prepared = Some((token, HardwarePlan::Bindings(plan)));
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
                    Command::OnboardPrepare { buttons, controls } => {
                        prepared = None;
                        if watching_plate {
                            ensure!(
                                read_plate(&mut hardware)?.buttons == Some(12),
                                "Attach the 12-button plate before saving mouse memory"
                            );
                        }
                        let mouse = hardware
                            .as_mut()
                            .context("Read mouse slots before saving")?;
                        let before = snapshot
                            .as_ref()
                            .context("Read mouse slots before saving")?;
                        let plan = mouse.prepare_controls(before, buttons, controls)?;
                        let token = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)?
                            .as_nanos()
                            .to_string();
                        emit(json!({"type":"onboard_prepared","token":token,"backup":plan.before}));
                        prepared = Some((token, HardwarePlan::Bindings(plan)));
                    }
                    Command::OnboardCommit { token } => {
                        let (expected, plan) =
                            prepared.take().context("No hardware save is prepared")?;
                        if watching_plate
                            || matches!(
                                &plan,
                                HardwarePlan::Creation(_) | HardwarePlan::Activation(_)
                            )
                        {
                            ensure!(
                                read_plate(&mut hardware)?.buttons == Some(12),
                                "Faceplate changed before save; no settings were written"
                            );
                        }
                        ensure!(
                            expected == token,
                            "Prepared hardware-save token does not match"
                        );
                        let mouse = hardware.as_mut().context("Hardware connection lost")?;
                        snapshot = None;
                        let (after, event) = match plan {
                            HardwarePlan::Activation(plan) => {
                                (mouse.commit_activation(plan)?, "onboard_activated")
                            }
                            HardwarePlan::Bindings(plan) => (mouse.commit(plan)?, "onboard_saved"),
                            HardwarePlan::Creation(plan) => {
                                (mouse.commit_creation(plan)?, "onboard_created")
                            }
                        };
                        emit(json!({"type":event,"snapshot":after}));
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
            Command::Apply {
                config: text,
                module_id,
            } => match config::parse(&text).and_then(|bindings| {
                if let Some(expected) = module_id {
                    ensure!(
                        device.is_some_and(|d| d.faceplate),
                        "Faceplate queries are not enabled for this model"
                    );
                    let plate = read_plate(&mut hardware)?;
                    ensure!(
                        plate.module_id == expected && plate.buttons.is_some(),
                        "Faceplate changed; wait for detection, then Apply again"
                    );
                }
                Ok(bindings)
            }) {
                Ok(bindings) => Some(bindings),
                Err(e) => {
                    emit(json!({"type":"error","message":format!("{e:#}")}));
                    continue;
                }
            },
            _ => unreachable!(),
        };
        if !watching_plate {
            hardware = None;
        }
        snapshot = None;
        prepared = None;
        if let Some(worker) = active.take() {
            worker.stop();
        }
        active = Some(worker(
            bindings,
            physical_id.clone(),
            device.map(|d| d.id.as_str()),
        ));
    }
    if let Some(worker) = active {
        worker.stop();
    }
    Ok(())
}
