use crate::config::{Bindings, Macro};
use anyhow::{Context, Result, ensure};
use evdev::{
    AttributeSet, Device, EventType, InputEvent, KeyCode, RelativeAxisCode, UinputAbsSetup,
    uinput::VirtualDevice,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    io,
    os::fd::AsRawFd,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

fn key_event(key: KeyCode, pressed: bool) -> InputEvent {
    InputEvent::new(EventType::KEY.0, key.0, i32::from(pressed))
}

fn is_pointer(key: KeyCode) -> bool {
    (0x100..0x160).contains(&key.0)
}

fn key_transition(held: &mut BTreeMap<KeyCode, usize>, key: KeyCode, pressed: bool) -> bool {
    let count = held.entry(key).or_default();
    if pressed {
        *count += 1;
        *count == 1
    } else if *count > 0 {
        *count -= 1;
        *count == 0
    } else {
        false
    }
}

struct MacroOutput {
    keyboard: VirtualDevice,
    pointer: VirtualDevice,
    held: BTreeMap<KeyCode, usize>,
}

impl MacroOutput {
    fn new(bindings: &Bindings) -> Result<Self> {
        let mut keys = AttributeSet::<KeyCode>::new();
        // Standard keyboard capabilities let the desktop recognize this as a keyboard.
        for k in 1..=248 {
            keys.insert(KeyCode(k));
        }
        let mut buttons = AttributeSet::<KeyCode>::new();
        buttons.insert(KeyCode::BTN_LEFT);
        buttons.insert(KeyCode::BTN_RIGHT);
        for action in bindings.values().flat_map(|m| &m.actions) {
            if is_pointer(action.key) {
                buttons.insert(action.key);
            } else {
                keys.insert(action.key);
            }
        }
        for key in bindings.values().filter_map(|m| m.remap) {
            if is_pointer(key) {
                buttons.insert(key);
            } else {
                keys.insert(key);
            }
        }
        let axes: AttributeSet<_> = [RelativeAxisCode::REL_X, RelativeAxisCode::REL_Y]
            .into_iter()
            .collect();
        Ok(Self {
            keyboard: VirtualDevice::builder()?
                .name("naga-macros keyboard")
                .with_keys(&keys)?
                .build()?,
            pointer: VirtualDevice::builder()?
                .name("naga-macros buttons")
                .with_keys(&buttons)?
                .with_relative_axes(&axes)?
                .build()?,
            held: BTreeMap::new(),
        })
    }

    fn send(&mut self, key: KeyCode, pressed: bool) -> io::Result<()> {
        // Track before emission so cleanup also attempts a release after a partial write.
        if !key_transition(&mut self.held, key, pressed) {
            return Ok(());
        }
        let target = if is_pointer(key) {
            &mut self.pointer
        } else {
            &mut self.keyboard
        };
        target.emit(&[key_event(key, pressed)])?;
        if !pressed {
            self.held.remove(&key);
        }
        Ok(())
    }

    fn repeat(&mut self, key: KeyCode) -> io::Result<()> {
        let target = if is_pointer(key) {
            &mut self.pointer
        } else {
            &mut self.keyboard
        };
        target.emit(&[InputEvent::new(EventType::KEY.0, key.0, 2)])
    }
}

impl Drop for MacroOutput {
    fn drop(&mut self) {
        for key in self.held.keys().copied().collect::<Vec<_>>() {
            self.held.insert(key, 1);
            let _ = self.send(key, false);
        }
    }
}

struct Source {
    path: PathBuf,
    device: Device,
    mirror: VirtualDevice,
    frame: Vec<InputEvent>,
    forwarded: BTreeSet<KeyCode>,
}

struct InterfaceCapabilities {
    keys: AttributeSet<KeyCode>,
    absolute: bool,
}

fn source_indices(capabilities: &[InterfaceCapabilities], bindings: &Bindings) -> BTreeSet<usize> {
    // Composite HID interfaces can advertise the same keyboard codes. Prefer
    // the ordinary keyboard interfaces when they cover all configured inputs.
    let standard_covers_all = bindings.keys().all(|key| {
        capabilities
            .iter()
            .any(|c| !c.absolute && c.keys.contains(*key))
    });
    capabilities
        .iter()
        .enumerate()
        .filter_map(|(index, c)| {
            (bindings.keys().any(|key| c.keys.contains(*key))
                && (!standard_covers_all || !c.absolute))
                .then_some(index)
        })
        .collect()
}

impl Source {
    fn new(path: PathBuf, device: Device) -> Result<Self> {
        let mut builder = VirtualDevice::builder()?.name("naga-macros passthrough");
        if let Some(keys) = device.supported_keys() {
            builder = builder.with_keys(keys)?;
        }
        if let Some(axes) = device.supported_relative_axes() {
            builder = builder.with_relative_axes(axes)?;
        }
        for (code, info) in device.get_absinfo()? {
            builder = builder.with_absolute_axis(&UinputAbsSetup::new(code, info))?;
        }
        builder = builder.with_properties(device.properties())?;
        let mirror = builder.build()?;
        Ok(Self {
            path,
            device,
            mirror,
            frame: Vec::new(),
            forwarded: BTreeSet::new(),
        })
    }

    fn forward(&mut self, event: InputEvent) -> io::Result<()> {
        if event.event_type() == EventType::SYNCHRONIZATION {
            if event.code() == 0 && !self.frame.is_empty() {
                self.mirror.emit(&self.frame)?;
                self.frame.clear();
            }
        } else if matches!(
            event.event_type(),
            EventType::KEY | EventType::RELATIVE | EventType::ABSOLUTE
        ) {
            if event.event_type() == EventType::KEY {
                if event.value() == 0 {
                    self.forwarded.remove(&KeyCode(event.code()));
                } else {
                    self.forwarded.insert(KeyCode(event.code()));
                }
            }
            self.frame.push(event);
        }
        Ok(())
    }
}

impl Drop for Source {
    fn drop(&mut self) {
        let releases: Vec<_> = self
            .forwarded
            .iter()
            .map(|k| key_event(*k, false))
            .collect();
        let _ = self.mirror.emit(&releases);
        let _ = self.device.ungrab();
    }
}

#[derive(Default)]
struct Router {
    pressed: BTreeSet<KeyCode>,
}

impl Router {
    /// Suppress all events for mapped buttons; trigger only a fresh press.
    fn route(&mut self, bindings: &Bindings, key: KeyCode, value: i32) -> (bool, bool) {
        if !bindings.contains_key(&key) {
            return (false, false);
        }
        let fresh = match value {
            1 => self.pressed.insert(key),
            0 => {
                self.pressed.remove(&key);
                false
            }
            _ => false,
        };
        (true, fresh)
    }
}

struct Playback {
    trigger: KeyCode,
    start: Instant,
    next: usize,
}

impl Playback {
    fn wait_ms(&self, m: &Macro, elapsed_ms: u128) -> i32 {
        let deadline = m
            .actions
            .get(self.next)
            .map_or(m.duration_ms, |action| action.at_ms);
        u128::from(deadline).saturating_sub(elapsed_ms).min(50) as i32
    }

    fn due<'a>(&mut self, m: &'a Macro, elapsed_ms: u128) -> &'a [crate::config::Action] {
        let first = self.next;
        while self.next < m.actions.len() && u128::from(m.actions[self.next].at_ms) <= elapsed_ms {
            self.next += 1;
        }
        &m.actions[first..self.next]
    }
}

pub(crate) fn wait_for_input(fds: &mut [libc::pollfd], timeout_ms: i32) -> io::Result<()> {
    // SAFETY: fds remains allocated for the call and contains borrowed live
    // source descriptors; poll only updates its revents fields.
    let result = unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, timeout_ms) };
    if result < 0 {
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
    Ok(())
}

pub fn run(
    devices: Vec<(PathBuf, Device)>,
    bindings: Bindings,
    running: Arc<AtomicBool>,
) -> Result<()> {
    run_inner(devices, bindings, running, false)
}

pub fn run_session(
    devices: Vec<(PathBuf, Device)>,
    bindings: Bindings,
    running: Arc<AtomicBool>,
) -> Result<()> {
    run_inner(devices, bindings, running, true)
}

fn run_inner(
    devices: Vec<(PathBuf, Device)>,
    bindings: Bindings,
    running: Arc<AtomicBool>,
    telemetry: bool,
) -> Result<()> {
    for key in bindings.keys() {
        ensure!(
            devices
                .iter()
                .any(|(_, d)| d.supported_keys().is_some_and(|keys| keys.contains(*key))),
            "Trigger {key:?} is not supported by any selected interface. Run monitor and update the config."
        );
    }
    let capabilities: Vec<_> = devices
        .iter()
        .map(|(_, device)| InterfaceCapabilities {
            keys: device
                .supported_keys()
                .map(|keys| keys.iter().collect())
                .unwrap_or_default(),
            absolute: device
                .supported_absolute_axes()
                .is_some_and(|axes| axes.iter().next().is_some()),
        })
        .collect();
    let selected = source_indices(&capabilities, &bindings);
    // Leave unrelated or redundant composite interfaces untouched.
    let devices: Vec<_> = devices
        .into_iter()
        .enumerate()
        .filter_map(|(index, device)| selected.contains(&index).then_some(device))
        .collect();
    // Build every output before grabbing any physical input; failure leaves input usable.
    let mut output = MacroOutput::new(&bindings).context("Creating virtual input devices; /dev/uinput must be available and writable (try sudo for testing)")?;
    let mut sources = devices
        .into_iter()
        .map(|(p, d)| Source::new(p, d))
        .collect::<Result<Vec<_>>>()?;
    // Allow the compositor to discover the virtual devices before forwarding events.
    thread::sleep(Duration::from_millis(500));
    for source in &mut sources {
        source.device.grab().with_context(|| {
            format!(
                "Grabbing {}; another remapper may already own it",
                source.path.display()
            )
        })?;
        // Discard events queued during setup, so old presses cannot launch macros.
        loop {
            match source.device.fetch_events() {
                Ok(events) => for _ in events {},
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(e) => return Err(e).context("Discarding startup input"),
            }
        }
        ensure!(
            source.device.get_key_state()?.iter().next().is_none(),
            "Release all mouse buttons before starting"
        );
    }
    let mut routers: Vec<_> = sources.iter().map(|_| Router::default()).collect();
    let mut poll_fds: Vec<_> = sources
        .iter()
        .map(|source| libc::pollfd {
            fd: source.device.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        })
        .collect();
    let mut active: Option<Playback> = None;
    if telemetry {
        crate::session::emit(serde_json::json!({"type":"state","state":"running"}));
    }
    eprintln!(
        "Running {} bindings. Mapped buttons are suppressed; other mouse input passes through. Ctrl+C stops.\nMacros run one at a time; presses while busy are discarded.",
        bindings.len()
    );
    // Reuse the batch allocation across interfaces and input frames. Holding
    // fetched events separately lets forwarding borrow the source safely.
    let mut events = Vec::new();
    while running.load(Ordering::Relaxed) {
        for (source, router) in sources.iter_mut().zip(&mut routers) {
            events.clear();
            match source.device.fetch_events() {
                Ok(fetched) => events.extend(fetched),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => continue,
                Err(e) => {
                    return Err(e).with_context(|| {
                        format!(
                            "Reading {}; mouse disconnected? Reconnect and restart.",
                            source.path.display()
                        )
                    });
                }
            }
            for event in events.drain(..) {
                if event.event_type() == EventType::KEY {
                    let key = KeyCode(event.code());
                    if telemetry {
                        crate::session::emit(
                            serde_json::json!({"type":"input","path":source.path,"key":format!("{key:?}"),"value":event.value()}),
                        );
                    }
                    let was_pressed = router.pressed.contains(&key);
                    let (suppress, fresh) = router.route(&bindings, key, event.value());
                    if let Some(target) = bindings.get(&key).and_then(|m| m.remap) {
                        if fresh {
                            output.send(target, true)?;
                        } else if event.value() == 0 && was_pressed {
                            output.send(target, false)?;
                        } else if event.value() == 2 && was_pressed {
                            output.repeat(target)?;
                        }
                        continue;
                    }
                    if fresh {
                        if active.is_none() {
                            active = Some(Playback {
                                trigger: key,
                                start: Instant::now(),
                                next: 0,
                            });
                        } else {
                            eprintln!("Ignored {key:?}: a macro is still running");
                        }
                    }
                    if suppress {
                        continue;
                    }
                }
                // Scan codes are metadata for the original key; never leak mapped key scan codes.
                if event.event_type() == EventType::MISC
                    && event.code() == evdev::MiscCode::MSC_SCAN.0
                {
                    continue;
                }
                source.forward(event)?;
            }
        }
        if let Some(playback) = &mut active {
            let m = &bindings[&playback.trigger];
            for action in playback.due(m, playback.start.elapsed().as_millis()) {
                output.send(action.key, action.pressed)?;
            }
            if playback.next == m.actions.len()
                && playback.start.elapsed().as_millis() >= u128::from(m.duration_ms)
            {
                active = None;
            }
        }
        // Input wakes immediately; timed macro actions wake at their deadline.
        // Bound idle waits so shutdown still releases output/grabs promptly.
        let timeout = active.as_ref().map_or(50, |playback| {
            playback.wait_ms(
                &bindings[&playback.trigger],
                playback.start.elapsed().as_millis(),
            )
        });
        wait_for_input(&mut poll_fds, timeout).context("Waiting for mouse input")?;
    }
    eprintln!("Stopped. Physical input restored.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn side_key_prefers_keyboard_over_composite_absolute_interface() {
        let bindings = crate::config::parse("[[binding]]\ntrigger='KEY_1'\nkey='KEY_B'").unwrap();
        let capabilities = vec![
            InterfaceCapabilities {
                keys: [KeyCode::BTN_LEFT, KeyCode::BTN_RIGHT]
                    .into_iter()
                    .collect(),
                absolute: false,
            },
            InterfaceCapabilities {
                keys: [KeyCode::KEY_1].into_iter().collect(),
                absolute: false,
            },
            InterfaceCapabilities {
                keys: [KeyCode::KEY_1].into_iter().collect(),
                absolute: true,
            },
        ];
        assert_eq!(
            source_indices(&capabilities, &bindings),
            BTreeSet::from([1])
        );
    }

    #[test]
    fn absolute_interface_is_retained_when_it_is_needed_for_a_binding() {
        let bindings = crate::config::parse("[[binding]]\ntrigger='KEY_1'\nkey='KEY_B'\n[[binding]]\ntrigger='BTN_SIDE'\nkey='KEY_C'").unwrap();
        let capabilities = vec![
            InterfaceCapabilities {
                keys: [KeyCode::KEY_1].into_iter().collect(),
                absolute: false,
            },
            InterfaceCapabilities {
                keys: [KeyCode::BTN_SIDE].into_iter().collect(),
                absolute: true,
            },
        ];
        assert_eq!(
            source_indices(&capabilities, &bindings),
            BTreeSet::from([0, 1])
        );
    }
    #[test]
    fn overlapping_bindings_keep_target_held_until_last_release() {
        let mut held = BTreeMap::new();
        let k = KeyCode::KEY_LEFTCTRL;
        assert!(key_transition(&mut held, k, true));
        assert!(!key_transition(&mut held, k, true));
        assert!(!key_transition(&mut held, k, false));
        assert!(key_transition(&mut held, k, false));
        assert!(!key_transition(&mut held, k, false));
    }
    #[test]
    fn routing_suppresses_repeats_and_both_edges() {
        let bindings =
            crate::config::parse("[[binding]]\ntrigger='KEY_1'\nsteps=[{tap='KEY_A'}]").unwrap();
        let mut router = Router::default();
        assert_eq!(router.route(&bindings, KeyCode::KEY_1, 1), (true, true));
        assert_eq!(router.route(&bindings, KeyCode::KEY_1, 1), (true, false));
        assert_eq!(router.route(&bindings, KeyCode::KEY_1, 2), (true, false));
        assert_eq!(router.route(&bindings, KeyCode::KEY_1, 0), (true, false));
        assert_eq!(
            router.route(&bindings, KeyCode::BTN_LEFT, 1),
            (false, false)
        );
        assert_eq!(router.route(&bindings, KeyCode::KEY_1, 1), (true, true));
    }
    #[test]
    fn playback_emits_each_action_once_at_its_deadline() {
        let bindings = crate::config::parse(
            "[[binding]]\ntrigger='KEY_1'\nsteps=[{tap='KEY_A'},{wait_ms=100},{tap='KEY_B'}]",
        )
        .unwrap();
        let m = &bindings[&KeyCode::KEY_1];
        let mut p = Playback {
            trigger: KeyCode::KEY_1,
            start: Instant::now(),
            next: 0,
        };
        assert_eq!(p.wait_ms(m, 0), 0);
        assert_eq!(p.due(m, 0).len(), 1);
        assert_eq!(p.wait_ms(m, 0), 20);
        assert_eq!(p.wait_ms(m, 19), 1);
        assert_eq!(p.wait_ms(m, 21), 0);
        assert!(p.due(m, 19).is_empty());
        assert_eq!(p.due(m, 20)[0].key, KeyCode::KEY_A);
        assert_eq!(p.wait_ms(m, 20), 50);
        assert!(p.due(m, 119).is_empty());
        assert_eq!(p.due(m, 1000).len(), 2);
        assert!(p.due(m, 2000).is_empty());
        assert_eq!(p.wait_ms(m, 2000), 0);
    }

    #[test]
    fn input_wait_reports_ready_and_disconnected_sources_without_a_device() -> io::Result<()> {
        use std::{io::Write, os::unix::net::UnixStream};
        let (source, mut writer) = UnixStream::pair()?;
        let mut fds = [libc::pollfd {
            fd: source.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        }];
        wait_for_input(&mut fds, 0)?;
        assert_eq!(fds[0].revents, 0);
        writer.write_all(&[1])?;
        wait_for_input(&mut fds, 50)?;
        assert_ne!(fds[0].revents & libc::POLLIN, 0);
        drop(writer);
        wait_for_input(&mut fds, 50)?;
        assert_ne!(fds[0].revents & libc::POLLHUP, 0);
        Ok(())
    }
}
