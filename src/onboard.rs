//! Naga V2 Pro hardware profiles. Only the twelve thumb-grid records are writable.
pub mod hidraw;

use anyhow::{Result, bail, ensure};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Identity {
    pub path: String,
    pub product: u16,
    pub serial: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Button {
    pub button: u8,
    pub category: u8,
    pub data: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub format: u8,
    pub device: Identity,
    pub slots: Vec<u8>,
    pub active: u8,
    pub slot: u8,
    pub mode: Vec<u8>,
    pub primary: Vec<Button>,
    pub buttons: Vec<Button>,
}

pub trait Transport {
    fn identity(&self) -> Identity;
    fn exchange(&mut self, class: u8, command: u8, payload: &[u8], echo: usize) -> Result<Vec<u8>>;
}

pub struct Mouse<T> {
    pub transport: T,
}

pub struct Prepared {
    pub before: Snapshot,
    pub desired: Vec<Button>,
}

fn slot_valid(slot: u8) -> Result<()> {
    ensure!(
        (1..=5).contains(&slot),
        "Onboard slot must be between 1 and 5"
    );
    Ok(())
}

pub fn validate_buttons(buttons: &[Button]) -> Result<()> {
    ensure!(
        buttons.len() == 12,
        "A hardware profile needs exactly twelve side-button actions"
    );
    let mut seen = BTreeSet::new();
    for button in buttons {
        ensure!(
            (1..=12).contains(&button.button) && seen.insert(button.button),
            "Invalid or duplicate physical side-button number"
        );
        match (button.category, button.data.as_slice()) {
            (0, []) => {}
            (1, [mouse]) if (1..=5).contains(mouse) => {}
            (2, [modifiers, usage])
                if (4..=0xa4).contains(usage) || (*usage == 0 && *modifiers != 0) => {}
            _ => bail!(
                "Unsupported onboard action for button {}; use a key or shortcut",
                button.button
            ),
        }
    }
    Ok(())
}

impl<T: Transport> Mouse<T> {
    fn writable_snapshot(fresh: &Snapshot) -> Result<()> {
        ensure!(
            fresh.mode == [0, 0] || fresh.mode == [3, 0],
            "Unsupported device mode; no writes made"
        );
        ensure!(
            fresh.primary
                == vec![
                    Button {
                        button: 1,
                        category: 1,
                        data: vec![1]
                    },
                    Button {
                        button: 2,
                        category: 1,
                        data: vec![2]
                    }
                ],
            "This slot does not have standard primary-click actions. Choose another initialized slot; primary clicks will not be rewritten."
        );
        ensure!(
            fresh.slots.contains(&fresh.active),
            "Active slot is not an initialized onboard slot; no changes made"
        );
        Ok(())
    }

    pub fn prepare_restore(&mut self, backup: Snapshot) -> Result<Prepared> {
        ensure!(
            backup.format == 1 && backup.buttons.len() == 12,
            "Invalid hardware backup format"
        );
        let mut seen = BTreeSet::new();
        for b in &backup.buttons {
            ensure!(
                (1..=12).contains(&b.button) && seen.insert(b.button) && b.data.len() <= 5,
                "Invalid side-button backup record"
            );
        }
        let fresh = self.read(Some(backup.slot))?;
        ensure!(
            !backup.device.serial.is_empty()
                && backup.device.serial == fresh.device.serial
                && backup.device.product == fresh.device.product,
            "This backup belongs to a different mouse or connection type"
        );
        Self::writable_snapshot(&fresh)?;
        Ok(Prepared {
            before: fresh,
            desired: backup.buttons,
        })
    }
    fn get_mode(&mut self) -> Result<Vec<u8>> {
        let bytes = self.transport.exchange(0, 0x84, &[0; 2], 0)?;
        ensure!(bytes.len() == 2, "Invalid device-mode reply");
        Ok(bytes)
    }

    fn get_slots(&mut self) -> Result<Vec<u8>> {
        let bytes = self.transport.exchange(5, 0x81, &[0; 6], 0)?;
        ensure!(
            bytes.len() == 6 && bytes[0] <= 5,
            "Unsupported onboard profile inventory: {} bytes, payload {:02x?}. No settings were changed. Run onboard-probe and share its output.",
            bytes.len(),
            bytes
        );
        let slots: Vec<_> = bytes[1..1 + usize::from(bytes[0])]
            .iter()
            .copied()
            .filter(|slot| *slot != 0)
            .collect();
        ensure!(
            !slots.is_empty(),
            "No initialized onboard profiles found. Profile creation is not supported yet; no changes were made."
        );
        let mut seen = BTreeSet::new();
        for slot in &slots {
            slot_valid(*slot)?;
            ensure!(seen.insert(*slot), "Duplicate onboard slot");
        }
        Ok(slots)
    }

    fn get_active(&mut self) -> Result<u8> {
        let bytes = self.transport.exchange(5, 0x84, &[0; 6], 0)?;
        ensure!(
            bytes.len() == 6 && bytes[0] <= 5,
            "Invalid active-profile reply"
        );
        Ok(bytes[0])
    }

    fn get_button(&mut self, slot: u8, id: u8, physical_number: u8) -> Result<Button> {
        let mut payload = [0; 10];
        payload[0] = slot;
        payload[1] = id;
        let bytes = self.transport.exchange(2, 0x8c, &payload, 3)?;
        ensure!(
            bytes.len() == 10 && bytes[..3] == payload[..3] && bytes[4] <= 5,
            "Invalid button-table reply for slot {slot}, id {id:#x}"
        );
        Ok(Button {
            button: physical_number,
            category: bytes[3],
            data: bytes[5..5 + usize::from(bytes[4])].to_vec(),
        })
    }

    fn set_button(&mut self, slot: u8, button: &Button) -> Result<()> {
        // This is the only mapping writer: no caller can address primary clicks.
        slot_valid(slot)?;
        ensure!(
            (1..=12).contains(&button.button) && button.data.len() <= 5,
            "Only thumb-grid records can be written"
        );
        let mut payload = [0; 10];
        payload[0] = slot;
        payload[1] = 0x3f + button.button;
        payload[3] = button.category;
        payload[4] = button.data.len() as u8;
        payload[5..5 + button.data.len()].copy_from_slice(&button.data);
        self.transport.exchange(2, 0x0c, &payload, 0)?;
        let actual = self.get_button(slot, payload[1], button.button)?;
        ensure!(
            actual == *button,
            "Read-back mismatch for side button {}",
            button.button
        );
        Ok(())
    }

    fn set_mode(&mut self, mode: &[u8]) -> Result<()> {
        ensure!(mode == [0, 0] || mode == [3, 0], "Unsupported device mode");
        self.transport.exchange(0, 4, mode, 0)?;
        ensure!(
            self.get_mode()? == mode,
            "Device mode did not read back correctly"
        );
        Ok(())
    }

    fn activate(&mut self, slot: u8) -> Result<()> {
        slot_valid(slot)?;
        self.transport.exchange(5, 4, &[slot], 0)?;
        ensure!(
            self.get_active()? == slot,
            "Active slot did not read back correctly"
        );
        Ok(())
    }

    pub fn read(&mut self, slot: Option<u8>) -> Result<Snapshot> {
        let mut device = self.transport.identity();
        let serial = self.transport.exchange(0, 0x82, &[0; 22], 0)?;
        ensure!(serial.len() == 22, "Invalid serial-number reply");
        device.serial = String::from_utf8(serial)?
            .trim_matches(char::from(0))
            .trim()
            .to_owned();
        ensure!(
            !device.serial.is_empty(),
            "Mouse did not return a serial number; refusing persistent writes without device identity"
        );
        let mode = self.get_mode()?;
        let slots = self.get_slots()?;
        let active = self.get_active()?;
        let slot = slot.unwrap_or_else(|| {
            if slots.contains(&active) {
                active
            } else {
                slots[0]
            }
        });
        slot_valid(slot)?;
        ensure!(
            slots.contains(&slot),
            "Slot {slot} is not initialized. No profile will be created or erased."
        );
        let primary = vec![self.get_button(slot, 1, 1)?, self.get_button(slot, 2, 2)?];
        let buttons = (1..=12)
            .map(|n| self.get_button(slot, 0x3f + n, n))
            .collect::<Result<Vec<_>>>()?;
        Ok(Snapshot {
            format: 1,
            device,
            slots,
            active,
            slot,
            mode,
            primary,
            buttons,
        })
    }

    pub fn prepare(&mut self, before: &Snapshot, desired: Vec<Button>) -> Result<Prepared> {
        validate_buttons(&desired)?;
        ensure!(before.format == 1, "Unsupported hardware backup format");
        let fresh = self.read(Some(before.slot))?;
        ensure!(
            &fresh == before,
            "Mouse state changed since Read slots. Read the mouse again before saving."
        );
        Self::writable_snapshot(&fresh)?;
        Ok(Prepared {
            before: fresh,
            desired,
        })
    }

    /// Called only after the GUI has durably saved the prepared backup and acknowledged it.
    pub fn commit(&mut self, prepared: Prepared) -> Result<Snapshot> {
        let before = prepared.before;
        ensure!(
            self.read(Some(before.slot))? == before,
            "Mouse changed after backup; read it again before saving"
        );
        let mut attempted = Vec::new();
        let result = (|| -> Result<Snapshot> {
            if before.mode != [0, 0] {
                self.set_mode(&[0, 0])?;
            }
            for button in &prepared.desired {
                let original = before
                    .buttons
                    .iter()
                    .find(|b| b.button == button.button)
                    .unwrap();
                if original != button {
                    attempted.push(original.clone());
                    self.set_button(before.slot, button)?;
                }
            }
            if before.active != before.slot {
                self.activate(before.slot)?;
            }
            let after = self.read(Some(before.slot))?;
            ensure!(
                after.mode == [0, 0]
                    && after.active == before.slot
                    && after.primary == before.primary,
                "Final onboard state did not verify"
            );
            for desired in &prepared.desired {
                ensure!(
                    after.buttons.contains(desired),
                    "Final button read-back mismatch"
                );
            }
            Ok(after)
        })();
        match result {
            Ok(snapshot) => Ok(snapshot),
            Err(error) => {
                let mut failures = Vec::new();
                for button in attempted.into_iter().rev() {
                    if let Err(e) = self.set_button(before.slot, &button) {
                        failures.push(e.to_string());
                    }
                }
                if let Err(e) = self.activate(before.active) {
                    failures.push(e.to_string());
                }
                if let Err(e) = self.set_mode(&before.mode) {
                    failures.push(e.to_string());
                }
                if failures.is_empty() {
                    bail!("Save failed; original bindings were restored: {error:#}");
                }
                bail!(
                    "Save failed: {error:#}. Rollback was incomplete: {}. Keep the saved backup and reconnect the mouse.",
                    failures.join("; ")
                )
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    struct Fake {
        buttons: BTreeMap<u8, Button>,
        writes: Vec<u8>,
        fail_once: Option<u8>,
        mode: Vec<u8>,
        active: u8,
    }
    impl Fake {
        fn new() -> Self {
            Self {
                buttons: (1..=12)
                    .map(|n| {
                        (
                            0x3f + n,
                            Button {
                                button: n,
                                category: 2,
                                data: vec![0, 0x1d + n],
                            },
                        )
                    })
                    .collect(),
                writes: vec![],
                fail_once: None,
                mode: vec![0, 0],
                active: 1,
            }
        }
    }
    impl Transport for Fake {
        fn identity(&self) -> Identity {
            Identity {
                path: "fake".into(),
                product: 0xa7,
                serial: String::new(),
            }
        }
        fn exchange(&mut self, class: u8, cmd: u8, p: &[u8], _: usize) -> Result<Vec<u8>> {
            Ok(match (class, cmd) {
                (0, 0x82) => {
                    let mut s = vec![0; 22];
                    s[..4].copy_from_slice(b"TEST");
                    s
                }
                (0, 0x84) => self.mode.clone(),
                (0, 4) => {
                    self.mode = p.to_vec();
                    p.to_vec()
                }
                (5, 0x81) => vec![5, 1, 2, 0, 0, 0],
                (5, 0x84) => vec![self.active, 0, 0, 0, 0, 0],
                (5, 4) => {
                    self.active = p[0];
                    p.to_vec()
                }
                (2, 0x8c) => {
                    let b = if p[1] <= 2 {
                        Button {
                            button: p[1],
                            category: 1,
                            data: vec![p[1]],
                        }
                    } else {
                        self.buttons[&p[1]].clone()
                    };
                    let mut r = p.to_vec();
                    r[3] = b.category;
                    r[4] = b.data.len() as u8;
                    r[5..5 + b.data.len()].copy_from_slice(&b.data);
                    r
                }
                (2, 0x0c) => {
                    assert!((0x40..=0x4b).contains(&p[1]), "primary write attempted");
                    self.writes.push(p[1]);
                    self.buttons.insert(
                        p[1],
                        Button {
                            button: p[1] - 0x3f,
                            category: p[3],
                            data: p[5..5 + usize::from(p[4])].to_vec(),
                        },
                    );
                    if self.fail_once == Some(p[1]) {
                        self.fail_once = None;
                        bail!("Injected failure after device accepted write");
                    }
                    p.to_vec()
                }
                _ => panic!("Unexpected command {class:x}/{cmd:x}"),
            })
        }
    }

    #[test]
    fn saves_only_changed_side_buttons_and_reads_them_back() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let before = mouse.read(None).unwrap();
        let mut desired = before.buttons.clone();
        desired[0].data = vec![0, 5];
        let p = mouse.prepare(&before, desired.clone()).unwrap();
        assert!(mouse.transport.writes.is_empty());
        let after = mouse.commit(p).unwrap();
        assert_eq!(after.buttons, desired);
        assert_eq!(mouse.transport.writes, vec![0x40]);
    }

    #[test]
    fn failed_ack_rolls_back_even_the_write_that_may_have_landed() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let before = mouse.read(None).unwrap();
        let mut desired = before.buttons.clone();
        desired[0].data = vec![0, 5];
        desired[1].data = vec![0, 6];
        let p = mouse.prepare(&before, desired).unwrap();
        mouse.transport.fail_once = Some(0x41);
        assert!(
            mouse
                .commit(p)
                .unwrap_err()
                .to_string()
                .contains("were restored")
        );
        assert_eq!(mouse.read(None).unwrap(), before);
        assert_eq!(mouse.transport.writes, vec![0x40, 0x41, 0x41, 0x40]);
    }

    #[test]
    fn saving_an_existing_inactive_slot_activates_it_in_normal_mode() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        mouse.transport.mode = vec![3, 0];
        let before = mouse.read(Some(2)).unwrap();
        assert_eq!(before.active, 1);
        let plan = mouse.prepare(&before, before.buttons.clone()).unwrap();
        let after = mouse.commit(plan).unwrap();
        assert_eq!(after.active, 2);
        assert_eq!(after.mode, vec![0, 0]);
        assert!(mouse.transport.writes.is_empty());
        assert!(mouse.read(Some(3)).is_err());
    }

    #[test]
    fn restore_is_device_bound_and_preserves_raw_actions() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let mut backup = mouse.read(None).unwrap();
        backup.device.serial = "OTHER".into();
        assert!(mouse.prepare_restore(backup.clone()).is_err());
        assert!(mouse.transport.writes.is_empty());
        backup.device.serial = "TEST".into();
        backup.buttons[0].category = 0x12;
        backup.buttons[0].data = vec![1, 2, 3];
        let plan = mouse.prepare_restore(backup.clone()).unwrap();
        let after = mouse.commit(plan).unwrap();
        assert_eq!(after.buttons, backup.buttons);
        assert_eq!(mouse.transport.writes, vec![0x40]);
    }

    #[test]
    fn invalid_or_stale_plan_never_writes() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let before = mouse.read(None).unwrap();
        let mut desired = before.buttons.clone();
        desired[0].button = 0;
        assert!(mouse.prepare(&before, desired).is_err());
        let p = mouse.prepare(&before, before.buttons.clone()).unwrap();
        mouse.transport.mode = vec![3, 0];
        assert!(mouse.commit(p).is_err());
        assert!(mouse.transport.writes.is_empty());
    }
}
