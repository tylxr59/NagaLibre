//! Naga V2 Pro profiles. Writers allow only the grid and explicit auxiliary controls.
pub mod activation;
pub mod creation;
pub mod echo_recovery;
pub mod haptic;
pub mod haptic_custom_trial;
pub mod haptic_probe;
pub mod haptic_transaction;
pub mod haptic_upload_replay;
pub mod haptic_views;
pub mod hidraw;
pub mod layer_transaction;
pub mod layer_write_probe;
pub mod layers;
pub mod macro_codec;
pub mod macro_plan;
pub mod macro_transaction;
pub mod macros;
mod native_actions;
pub mod slot_trial;

use anyhow::{Context, Result, bail, ensure};
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
    /// Original category, length and five data bytes when not canonically encoded.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub raw_record: Option<[u8; 7]>,
}

impl Button {
    fn same_action(&self, other: &Self) -> bool {
        self.button == other.button && self.category == other.category && self.data == other.data
    }

    fn from_record(button: u8, record: [u8; 7]) -> Result<Self> {
        ensure!(record[1] <= 5, "Invalid button action length");
        // Physical USB captures show keyboard length=1 while the modifier and
        // HID usage still occupy both bytes, matching observed key events.
        let length = if record[0] == 2 && record[1] == 1 {
            2
        } else {
            usize::from(record[1])
        };
        let mut decoded = Self {
            button,
            category: record[0],
            data: record[2..2 + length].to_vec(),
            raw_record: None,
        };
        if decoded.record()? != record {
            decoded.raw_record = Some(record);
        }
        Ok(decoded)
    }

    fn record(&self) -> Result<[u8; 7]> {
        ensure!(self.data.len() <= 5, "Button action is too long");
        if let Some(raw) = self.raw_record {
            let decoded = Self::from_record(self.button, raw)?;
            ensure!(
                decoded.category == self.category && decoded.data == self.data,
                "Raw button record does not match decoded action"
            );
            return Ok(raw);
        }
        let mut record = [0; 7];
        record[0] = self.category;
        record[1] = self.data.len() as u8;
        record[2..2 + self.data.len()].copy_from_slice(&self.data);
        Ok(record)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub format: u8,
    pub device: Identity,
    pub slots: Vec<u8>,
    /// Reported capacity, independent of the initialized slot list. Old backups
    /// omit this field; absence must not be interpreted as a guessed capacity.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_capacity: Option<u8>,
    pub active: u8,
    pub slot: u8,
    pub mode: Vec<u8>,
    pub primary: Vec<Button>,
    pub buttons: Vec<Button>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub controls: Vec<Button>,
}

// Logical positions 13..15 are separate from the interchangeable thumb grid.
fn control_id(button: u8) -> Result<u8> {
    match button {
        1..=12 => Ok(0x3f + button),
        13..=16 => crate::devices::naga_defaults()
            .controls
            .iter()
            .find(|c| c.button == button && [0x34, 0x35, 0x6d, 0x60].contains(&c.wire_id))
            .map(|c| c.wire_id)
            .ok_or_else(|| anyhow::anyhow!("Unrecognized auxiliary control")),
        _ => bail!("Only grid and registered auxiliary controls can be written"),
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SlotInventory {
    pub capacity: u8,
    pub initialized: Vec<u8>,
    pub active: u8,
}

pub trait Transport {
    fn identity(&self) -> Identity;
    fn exchange(&mut self, class: u8, command: u8, payload: &[u8], echo: usize) -> Result<Vec<u8>>;
}

pub struct Mouse<T> {
    pub transport: T,
}

#[derive(Clone, Copy)]
enum MappingLayer {
    Normal = 0,
    Hypershift = 1,
}

pub struct Prepared {
    pub before: Snapshot,
    pub desired: Vec<Button>,
    verification: Verification,
}

#[derive(Clone, Copy)]
enum Verification {
    Action,
    Wire,
}

impl Verification {
    fn matches(self, actual: &Button, expected: &Button) -> Result<bool> {
        Ok(match self {
            Self::Action => actual.same_action(expected),
            Self::Wire => {
                actual.button == expected.button && actual.record()? == expected.record()?
            }
        })
    }
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
        button.record()?;
        ensure!(
            (1..=12).contains(&button.button) && seen.insert(button.button),
            "Invalid or duplicate physical side-button number"
        );
        validate_action(button)?;
    }
    Ok(())
}

fn validate_action(button: &Button) -> Result<()> {
    button.record()?;
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
                        data: vec![1],
                        raw_record: None,
                    },
                    Button {
                        button: 2,
                        category: 1,
                        data: vec![2],
                        raw_record: None,
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
            b.record()?;
            ensure!(
                (1..=12).contains(&b.button) && seen.insert(b.button) && b.data.len() <= 5,
                "Invalid side-button backup record"
            );
        }
        let mut desired = backup.buttons.clone();
        let mut controls = BTreeSet::new();
        for b in &backup.controls {
            ensure!(
                (13..=16).contains(&b.button) && controls.insert(b.button),
                "Invalid control backup"
            );
            b.record()?;
            desired.push(b.clone());
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
            desired,
            verification: Verification::Wire,
        })
    }
    fn get_mode(&mut self) -> Result<Vec<u8>> {
        let bytes = self.transport.exchange(0, 0x84, &[0; 2], 0)?;
        ensure!(bytes.len() == 2, "Invalid device-mode reply");
        Ok(bytes)
    }

    pub fn slot_inventory(&mut self) -> Result<SlotInventory> {
        let bytes = self.transport.exchange(5, 0x81, &[0; 6], 0)?;
        ensure!(
            !bytes.is_empty() && (1..=5).contains(&bytes[0]) && bytes.len() <= 6,
            "Unsupported onboard profile inventory: {} bytes, payload {:02x?}. No settings were changed. Run onboard-probe and share its output.",
            bytes.len(),
            bytes
        );
        // The first byte is capacity, not the number of returned entries.
        // Wired hardware returned [5, 1, 2] with data_size=3: absent entries
        // need not be zero-padded to the six-byte request size.
        let slots: Vec<_> = bytes[1..]
            .iter()
            .copied()
            .filter(|slot| *slot != 0)
            .collect();
        let mut seen = BTreeSet::new();
        for slot in &slots {
            slot_valid(*slot)?;
            ensure!(*slot <= bytes[0], "Onboard slot exceeds reported capacity");
            ensure!(seen.insert(*slot), "Duplicate onboard slot");
        }
        let active = self.get_active()?;
        ensure!(active <= bytes[0], "Active slot exceeds reported capacity");
        Ok(SlotInventory {
            capacity: bytes[0],
            initialized: slots,
            active,
        })
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
        self.get_layer_button(slot, id, physical_number, MappingLayer::Normal)
    }

    fn get_layer_button(
        &mut self,
        slot: u8,
        id: u8,
        physical_number: u8,
        layer: MappingLayer,
    ) -> Result<Button> {
        let mut payload = [0; 10];
        payload[0] = slot;
        payload[1] = id;
        payload[2] = layer as u8;
        let bytes = self
            .transport
            .exchange(2, 0x8c, &payload, 3)
            .with_context(|| {
                format!(
                    "Reading slot {slot}, button {physical_number} (wire {id:#04x}), layer {}",
                    layer as u8
                )
            })?;
        ensure!(
            bytes.len() == 10 && bytes[..3] == payload[..3] && bytes[4] <= 5,
            "Invalid button-table reply for slot {slot}, id {id:#x}, layer {}",
            layer as u8
        );
        Button::from_record(physical_number, bytes[3..10].try_into().unwrap())
    }

    fn set_button(&mut self, slot: u8, button: &Button, verification: Verification) -> Result<()> {
        // This is the only mapping writer: no caller can address primary clicks.
        slot_valid(slot)?;
        ensure!(button.data.len() <= 5, "Button action too long");
        let mut payload = [0; 10];
        payload[0] = slot;
        payload[1] = control_id(button.button)?;
        payload[3..10].copy_from_slice(&button.record()?);
        self.transport.exchange(2, 0x0c, &payload, 0)?;
        let actual = self.get_button(slot, payload[1], button.button)?;
        ensure!(
            verification.matches(&actual, button)?,
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
        Ok(self.read_snapshot(slot, false)?.0)
    }

    fn read_with_layer_echoes(
        &mut self,
        slot: Option<u8>,
    ) -> Result<(Snapshot, Vec<layers::LayerEcho>)> {
        self.read_snapshot(slot, true)
    }

    fn read_snapshot(
        &mut self,
        slot: Option<u8>,
        paired: bool,
    ) -> Result<(Snapshot, Vec<layers::LayerEcho>)> {
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
        let inventory = self.slot_inventory()?;
        let slots = inventory.initialized;
        let active = inventory.active;
        ensure!(
            !slots.is_empty(),
            "No initialized onboard profiles found. Creating the first profile is unsupported; no changes were made."
        );
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
        let mut echoes = Vec::new();
        let mut read_control = |mouse: &mut Self, number: u8| -> Result<Button> {
            let id = control_id(number)?;
            if paired && device.product == 0xa7 {
                // Wired hardware proved distinct requested action records even
                // when both getters report the last secondary write's selector.
                // This scope excludes primary reads and ordinary snapshots.
                let mut request = [0; 10];
                request[..2].copy_from_slice(&[slot, id]);
                let bytes = mouse.transport.exchange(2,0x8c,&request,2)
                    .with_context(|| format!("Reading slot {slot}, button {number} (wire {id:#04x}), requested layer 0"))?;
                ensure!(
                    bytes.len() == 10 && bytes[..2] == request[..2] && bytes[2] <= 1,
                    "Invalid paired normal mapping reply"
                );
                echoes.push(layers::LayerEcho {
                    button: number,
                    layer: bytes[2],
                });
                Button::from_record(number, bytes[3..].try_into().unwrap())
            } else {
                let button = mouse.get_button(slot, id, number)?;
                if paired {
                    echoes.push(layers::LayerEcho {
                        button: number,
                        layer: 0,
                    });
                }
                Ok(button)
            }
        };
        let buttons = (1..=12)
            .map(|n| read_control(self, n))
            .collect::<Result<Vec<_>>>()?;
        let controls = crate::devices::naga_defaults()
            .controls
            .iter()
            .map(|c| read_control(self, c.button))
            .collect::<Result<Vec<_>>>()?;
        Ok((
            Snapshot {
                format: 1,
                device,
                slots,
                slot_capacity: Some(inventory.capacity),
                active,
                slot,
                mode,
                primary,
                buttons,
                controls,
            },
            echoes,
        ))
    }

    pub fn prepare(&mut self, before: &Snapshot, mut desired: Vec<Button>) -> Result<Prepared> {
        validate_buttons(&desired)?;
        ensure!(before.format == 1, "Unsupported hardware backup format");
        let fresh = self.read(Some(before.slot))?;
        ensure!(
            &fresh == before,
            "Mouse state changed since Read slots. Read the mouse again before saving."
        );
        Self::writable_snapshot(&fresh)?;
        // GUI drafts describe actions. Retain the exact hardware representation
        // for unchanged actions rather than normalizing their length/padding.
        for button in &mut desired {
            if let Some(original) = fresh.buttons.iter().find(|b| b.same_action(button)) {
                *button = original.clone();
            }
        }
        Ok(Prepared {
            before: fresh,
            desired,
            verification: Verification::Action,
        })
    }

    pub fn prepare_controls(
        &mut self,
        before: &Snapshot,
        desired: Vec<Button>,
        controls: Vec<Button>,
    ) -> Result<Prepared> {
        let mut seen = BTreeSet::new();
        for button in &controls {
            ensure!(
                (13..=16).contains(&button.button) && seen.insert(button.button),
                "Invalid or duplicate wheel control"
            );
            // Device167 factory control functions are accepted only at their
            // explicitly mapped physical positions, not as arbitrary actions.
            let factory = crate::devices::naga_defaults().controls.iter().any(|c| {
                c.button == button.button
                    && c.binding.category == button.category
                    && c.binding.data == button.data
            });
            if factory {
                button.record()?;
            } else {
                validate_action(button)?;
            }
        }
        let mut plan = self.prepare(before, desired)?;
        for mut button in controls {
            let original = before
                .controls
                .iter()
                .find(|b| b.button == button.button)
                .ok_or_else(|| anyhow::anyhow!("Read wheel controls before saving"))?;
            if original.same_action(&button) {
                button = original.clone();
            }
            plan.desired.push(button);
        }
        Ok(plan)
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
                    .chain(before.controls.iter())
                    .find(|b| b.button == button.button)
                    .unwrap();
                if !prepared.verification.matches(original, button)? {
                    attempted.push(original.clone());
                    self.set_button(before.slot, button, prepared.verification)?;
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
                let original = before
                    .buttons
                    .iter()
                    .chain(before.controls.iter())
                    .find(|b| b.button == desired.button)
                    .unwrap();
                let actual = after
                    .buttons
                    .iter()
                    .chain(after.controls.iter())
                    .find(|b| b.button == desired.button)
                    .unwrap();
                // Changed GUI actions may be encoded differently by firmware.
                // Unchanged actions, explicit restores and rollback stay exact.
                let verification = if original.same_action(desired) {
                    Verification::Wire
                } else {
                    prepared.verification
                };
                ensure!(
                    verification.matches(actual, desired)?,
                    "Final button read-back mismatch"
                );
            }
            for original in &before.controls {
                if !prepared.desired.iter().any(|b| b.button == original.button) {
                    ensure!(
                        after.controls.iter().any(|b| b == original),
                        "Untouched wheel control changed"
                    );
                }
            }
            Ok(after)
        })();
        match result {
            Ok(snapshot) => Ok(snapshot),
            Err(error) => {
                let mut failures = Vec::new();
                for button in attempted.into_iter().rev() {
                    if let Err(e) = self.set_button(before.slot, &button, Verification::Wire) {
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
        controls: BTreeMap<u8, Button>,
        writes: Vec<u8>,
        fail_once: Option<u8>,
        mode: Vec<u8>,
        active: u8,
        inventory: Vec<u8>,
        wire_writes: Vec<(u8, [u8; 7])>,
        reencode_once: bool,
        requests: Vec<(u8, u8)>,
        allocation_fails: bool,
        deletion_fails: bool,
        allocation_activates: bool,
        blank_new_primary: bool,
        product: u16,
        fail_activations: usize,
    }
    impl Fake {
        fn new() -> Self {
            Self {
                controls: [(13, 0x34), (14, 0x35), (15, 0x6d), (16, 0x60)]
                    .into_iter()
                    .map(|(button, id)| {
                        (
                            id,
                            Button {
                                button,
                                category: 0,
                                data: vec![],
                                raw_record: None,
                            },
                        )
                    })
                    .collect(),
                buttons: (1..=12)
                    .map(|n| {
                        (
                            0x3f + n,
                            Button {
                                button: n,
                                category: 2,
                                data: vec![0, 0x1d + n],
                                raw_record: None,
                            },
                        )
                    })
                    .collect(),
                writes: vec![],
                fail_once: None,
                mode: vec![0, 0],
                active: 1,
                inventory: vec![5, 1, 2, 0, 0, 0],
                wire_writes: vec![],
                reencode_once: false,
                requests: Vec::new(),
                allocation_fails: false,
                deletion_fails: false,
                allocation_activates: false,
                blank_new_primary: false,
                product: 0xa7,
                fail_activations: 0,
            }
        }

        fn captured_factory() -> Self {
            let mut fake = Self::new();
            let usages = [
                0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2d, 0x2e,
            ];
            for (i, usage) in usages.into_iter().enumerate() {
                let n = i as u8 + 1;
                let length = if n <= 2 { 2 } else { 1 };
                fake.buttons.insert(
                    0x3f + n,
                    Button::from_record(n, [2, length, 0, usage, 0, 0, 0]).unwrap(),
                );
            }
            fake.inventory = vec![5, 1, 2];
            fake
        }

        fn gui_factory() -> Vec<Button> {
            Self::captured_factory()
                .buttons
                .into_values()
                .map(|mut b| {
                    b.raw_record = None;
                    b
                })
                .collect()
        }
    }
    impl Transport for Fake {
        fn identity(&self) -> Identity {
            Identity {
                path: "fake".into(),
                product: self.product,
                serial: String::new(),
            }
        }
        fn exchange(&mut self, class: u8, cmd: u8, p: &[u8], _: usize) -> Result<Vec<u8>> {
            self.requests.push((class, cmd));
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
                (5, 0x81) => self.inventory.clone(),
                (5, 0x84) => vec![self.active, 0, 0, 0, 0, 0],
                (5, 2) => {
                    assert!(!self.inventory.contains(&p[0]));
                    self.inventory.retain(|n| *n != 0);
                    self.inventory.push(p[0]);
                    if self.allocation_activates {
                        self.active = p[0];
                    }
                    if self.allocation_fails {
                        bail!("Allocation accepted but acknowledgement lost");
                    }
                    p.to_vec()
                }
                (5, 3) => {
                    assert!(p[0] > 2, "Deleting an original slot");
                    if self.deletion_fails {
                        bail!("Deletion failed");
                    }
                    self.inventory.retain(|n| *n != p[0]);
                    p.to_vec()
                }
                (5, 4) => {
                    self.active = p[0];
                    if self.fail_activations > 0 {
                        self.fail_activations -= 1;
                        bail!("Activation accepted but acknowledgement lost");
                    }
                    p.to_vec()
                }
                (2, 0x8c) => {
                    assert_eq!(p[2], 0, "Normal reads must not select Hypershift");
                    let b = if p[0] == 3 && p[1] == 1 && self.blank_new_primary {
                        Button {
                            button: 1,
                            category: 0,
                            data: vec![],
                            raw_record: None,
                        }
                    } else if p[1] <= 3 {
                        Button {
                            button: p[1],
                            category: 1,
                            data: vec![p[1]],
                            raw_record: None,
                        }
                    } else if let Some(control) = self.controls.get(&p[1]) {
                        control.clone()
                    } else {
                        self.buttons[&p[1]].clone()
                    };
                    let mut r = p.to_vec();
                    r[3..10].copy_from_slice(&b.record()?);
                    r
                }
                (2, 0x0c) => {
                    assert_eq!(p[2], 0, "Existing writers must remain normal-only");
                    assert!(
                        (0x40..=0x4b).contains(&p[1]) || [0x34, 0x35, 0x6d, 0x60].contains(&p[1]),
                        "primary write attempted"
                    );
                    self.writes.push(p[1]);
                    let mut record: [u8; 7] = p[3..10].try_into().unwrap();
                    self.wire_writes.push((p[1], record));
                    if self.reencode_once && record[0] == 2 && record[1] == 2 {
                        self.reencode_once = false;
                        record[1] = 1;
                    }
                    if let Some(control) = self.controls.get_mut(&p[1]) {
                        *control = Button::from_record(control.button, record)?;
                    } else {
                        self.buttons
                            .insert(p[1], Button::from_record(p[1] - 0x3f, record)?);
                    }
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

    // Independent banks backed by captured noncanonical keyboard and tilt records.
    struct BankFake {
        slots: BTreeMap<u8, Fake>,
        secondary: BTreeMap<(u8, u8), [u8; 7]>,
        writes: Vec<(u8, u8, u8)>,
        lose_ack: bool,
        alias: bool,
        reencode: bool,
        block_restore: bool,
        normal_echo_one: bool,
        echo_stuck: bool,
        tag_last_write: bool,
        operations: Vec<(u8, u8, Vec<u8>)>,
        corrupt_secondary_on_allocate: bool,
    }
    impl BankFake {
        fn new() -> Self {
            let slots: BTreeMap<_, _> = [1, 2]
                .into_iter()
                .map(|slot| (slot, Fake::captured_factory()))
                .collect();
            let mut secondary = BTreeMap::new();
            for (slot, normal) in &slots {
                for (id, button) in normal.buttons.iter().chain(&normal.controls) {
                    let mut record = button.record().unwrap();
                    if *id == 0x40 || *id == 0x41 {
                        record[1] = 1;
                    }
                    if *id == 0x34 {
                        record = [14, 1, 104, 0, 20, 0, 0];
                    }
                    secondary.insert((*slot, *id), record);
                }
            }
            Self {
                slots,
                secondary,
                writes: vec![],
                lose_ack: false,
                alias: false,
                reencode: false,
                block_restore: false,
                normal_echo_one: false,
                echo_stuck: false,
                tag_last_write: true,
                operations: vec![],
                corrupt_secondary_on_allocate: false,
            }
        }
    }
    impl Transport for BankFake {
        fn identity(&self) -> Identity {
            self.slots[&1].identity()
        }
        fn exchange(&mut self, class: u8, cmd: u8, p: &[u8], echo: usize) -> Result<Vec<u8>> {
            self.operations.push((class, cmd, p.to_vec()));
            if (class, cmd) == (5, 2) {
                let normal = Fake::captured_factory();
                for (id, b) in normal.buttons.iter().chain(&normal.controls) {
                    self.secondary.insert((p[0], *id), b.record()?);
                }
                self.slots.insert(p[0], normal);
                if self.corrupt_secondary_on_allocate {
                    self.secondary.get_mut(&(2, 0x34)).unwrap()[6] ^= 1;
                }
                return self
                    .slots
                    .get_mut(&1)
                    .unwrap()
                    .exchange(class, cmd, p, echo);
            }
            if (class, cmd) == (5, 3) {
                let result = self
                    .slots
                    .get_mut(&1)
                    .unwrap()
                    .exchange(class, cmd, p, echo)?;
                self.slots.remove(&p[0]);
                self.secondary.retain(|(slot, _), _| *slot != p[0]);
                return Ok(result);
            }
            if (class, cmd) == (0, 0xb9) {
                return Ok(vec![3]);
            }
            if class == 2 && matches!(cmd, 0x8c | 0x0c) {
                assert!(p[2] <= 1);
                if cmd == 0x0c {
                    assert!(
                        (0x40..=0x4b).contains(&p[1]) || [0x34, 0x35, 0x6d, 0x60].contains(&p[1]),
                        "primary write"
                    );
                    self.writes.push((p[0], p[2], p[1]));
                    if self.block_restore && self.writes.len() > 1 {
                        bail!("Recovery transport unavailable");
                    }
                }
                if p[2] == 1 {
                    if cmd == 0x0c {
                        if self.tag_last_write && p[0] == 1 && p[1] == 0x40 {
                            self.normal_echo_one = true;
                        }
                        if self.alias {
                            let mut normal = p.to_vec();
                            normal[2] = 0;
                            self.slots
                                .get_mut(&p[0])
                                .unwrap()
                                .exchange(class, cmd, &normal, echo)?;
                        } else {
                            let mut record: [u8; 7] = p[3..].try_into().unwrap();
                            if self.reencode && record[0] == 2 {
                                record[1] = 1;
                            }
                            self.secondary.insert((p[0], p[1]), record);
                        }
                        if self.lose_ack {
                            self.lose_ack = false;
                            bail!("Write landed but acknowledgement lost");
                        }
                    }
                    let mut reply = p.to_vec();
                    reply[2] = u8::from(self.normal_echo_one && p[0] == 1 && p[1] == 0x40);
                    reply[3..].copy_from_slice(&self.secondary[&(p[0], p[1])]);
                    return Ok(reply);
                }
                if cmd == 0x0c && p[0] == 1 && p[1] == 0x40 && !self.echo_stuck {
                    self.normal_echo_one = false;
                }
                let mut result = self
                    .slots
                    .get_mut(&p[0])
                    .unwrap()
                    .exchange(class, cmd, p, echo)?;
                if self.normal_echo_one && cmd == 0x8c && p[0] == 1 && p[1] == 0x40 {
                    if echo >= 3 {
                        bail!(
                            "No matching reply to mouse command 02/8c; mapping echo: slot 1, wire button 0x40, layer 1"
                        );
                    }
                    result[2] = 1;
                }
                return Ok(result);
            }
            self.slots
                .get_mut(&1)
                .unwrap()
                .exchange(class, cmd, p, echo)
        }
    }
    #[test]
    fn selector_inspection_preserves_observed_reverse_echo_without_inventing_bank_identity() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        mouse.transport.normal_echo_one = true;
        assert!(mouse.read(None).is_err());
        let paired = mouse.read_layers(None).unwrap();
        assert_eq!(paired.normal_echoes[0].layer, 1);
        let evidence = mouse.inspect_mapping_selectors().unwrap();
        assert_eq!(evidence["bank_identity_verified"], false);
        let records = evidence["records"].as_array().unwrap();
        assert_eq!(records.len(), 35); // 3 normal primary + 16 per selector.
        let first = records
            .iter()
            .find(|r| r["wire"] == 0x40 && r["requested_layer"] == 0)
            .unwrap();
        assert_eq!(first["echoed_layer"], 1);
        assert_eq!(first["record"], serde_json::json!([2, 2, 0, 30, 0, 0, 0]));
        let secondary = records
            .iter()
            .find(|r| r["wire"] == 0x40 && r["requested_layer"] == 1)
            .unwrap();
        assert_eq!(secondary["echoed_layer"], 1);
        assert_eq!(
            secondary["record"],
            serde_json::json!([2, 1, 0, 30, 0, 0, 0])
        );
        assert!(
            serde_json::from_value::<layer_transaction::LayerBackup>(evidence.clone()).is_err()
        );
        assert!(serde_json::from_value::<layers::LayerReadback>(evidence).is_err());
        assert!(mouse.transport.writes.is_empty());
    }
    #[test]
    fn selector_inspection_rejects_changes_and_wrong_plates_without_writes() {
        for bad_plate in [false, true] {
            let mut transport = LayerFake::new();
            transport.change_secondary = !bad_plate;
            if bad_plate {
                transport.initial_plate = 4;
            }
            let mut mouse = Mouse { transport };
            assert!(mouse.inspect_mapping_selectors().is_err());
            assert!(mouse.transport.normal.writes.is_empty());
            assert!(
                mouse
                    .transport
                    .requests
                    .iter()
                    .all(|(class, cmd, _)| (*class, *cmd) != (2, 0x0c))
            );
        }
    }

    #[test]
    fn echo_recovery_writes_one_original_normal_record_and_checks_both_banks_even_on_lost_ack() {
        for lose_ack in [false, true] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let original = mouse.read_layers(None).unwrap();
            let backup = mouse
                .prepare_layers(&original, vec![])
                .unwrap()
                .backup()
                .clone();
            mouse.transport.normal_echo_one = true;
            let evidence = mouse.inspect_mapping_selectors().unwrap();
            if lose_ack {
                mouse.transport.slots.get_mut(&1).unwrap().fail_once = Some(0x40);
            }
            let journal = trial_journal();
            mouse
                .recover_grid_one_echo(&backup, &evidence, &journal)
                .unwrap();
            assert_eq!(mouse.transport.writes, [(1, 0, 0x40)]);
            assert_eq!(mouse.read_layers(None).unwrap(), original);
            let text = std::fs::read_to_string(&journal).unwrap();
            assert!(text.contains("paired_backup_restored_exactly"));
            std::fs::remove_file(journal).unwrap();
        }
    }
    #[test]
    fn echo_recovery_refuses_stale_evidence_other_slot_changes_and_changed_actions() {
        for case in 0..3 {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let original = mouse.read_layers(None).unwrap();
            let backup = mouse
                .prepare_layers(&original, vec![])
                .unwrap()
                .backup()
                .clone();
            mouse.transport.normal_echo_one = true;
            let mut evidence = mouse.inspect_mapping_selectors().unwrap();
            match case {
                0 => {
                    evidence["records"][3]["echoed_layer"] = serde_json::json!(0);
                }
                1 => {
                    mouse.transport.secondary.get_mut(&(2, 0x34)).unwrap()[6] = 1;
                }
                _ => {
                    mouse.transport.secondary.get_mut(&(1, 0x40)).unwrap()[3] = 5;
                    evidence = mouse.inspect_mapping_selectors().unwrap();
                }
            }
            let journal = trial_journal();
            assert!(
                mouse
                    .recover_grid_one_echo(&backup, &evidence, &journal)
                    .is_err()
            );
            assert!(mouse.transport.writes.is_empty());
            assert!(!journal.exists());
        }
    }
    #[test]
    fn echo_recovery_existing_or_unwritable_journal_prevents_all_writes() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let original = mouse.read_layers(None).unwrap();
        let backup = mouse
            .prepare_layers(&original, vec![])
            .unwrap()
            .backup()
            .clone();
        mouse.transport.normal_echo_one = true;
        let evidence = mouse.inspect_mapping_selectors().unwrap();
        let journal = trial_journal();
        std::fs::write(&journal, b"existing").unwrap();
        for path in [journal.clone(), journal.join("missing/attempt.jsonl")] {
            assert!(
                mouse
                    .recover_grid_one_echo(&backup, &evidence, &path)
                    .is_err()
            );
        }
        assert!(mouse.transport.writes.is_empty());
        std::fs::remove_file(journal).unwrap();
    }
    #[test]
    fn echo_recovery_never_retries_or_claims_success_if_normal_echo_remains_wrong() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let original = mouse.read_layers(None).unwrap();
        let backup = mouse
            .prepare_layers(&original, vec![])
            .unwrap()
            .backup()
            .clone();
        mouse.transport.normal_echo_one = true;
        mouse.transport.echo_stuck = true;
        let evidence = mouse.inspect_mapping_selectors().unwrap();
        let journal = trial_journal();
        let error = format!(
            "{:#}",
            mouse
                .recover_grid_one_echo(&backup, &evidence, &journal)
                .unwrap_err()
        );
        assert!(error.contains("restoration remains unverified"), "{error}");
        assert!(
            mouse
                .recover_grid_one_echo(&backup, &evidence, &journal)
                .is_err()
        );
        assert_eq!(mouse.transport.writes, [(1, 0, 0x40)]);
        let text = std::fs::read_to_string(&journal).unwrap();
        assert!(text.contains("repair_unverified"));
        assert!(!text.contains("paired_backup_restored_exactly"));
        std::fs::remove_file(journal).unwrap();
    }

    #[test]
    fn write_probe_captures_shared_echo_but_separate_actions_then_restores_before_exit() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let backup = mouse
            .prepare_layers(&before, vec![])
            .unwrap()
            .backup()
            .clone();
        mouse.transport.tag_last_write = true;
        let journal = trial_journal();
        let report = mouse.layer_write_probe(&backup, &journal, false).unwrap();
        assert_eq!(report["restored_exactly"], true);
        assert_eq!(report["result"]["observed_selector_1_b_only"], true);
        let records = report["result"]["observations"]["records"]
            .as_array()
            .unwrap();
        for record in records.iter().filter(|r| r["logical"] == 1) {
            assert_eq!(record["echoed_layer"], 1);
        }
        assert_eq!(
            mouse.transport.writes,
            [(1, 1, 0x40), (1, 1, 0x40), (1, 0, 0x40)]
        );
        assert_eq!(mouse.read_layers(None).unwrap(), before);
        assert!(mouse.layer_write_probe(&backup, &journal, false).is_err());
        assert_eq!(mouse.transport.writes.len(), 3);
        std::fs::remove_file(journal).unwrap();
    }
    #[test]
    fn write_probe_restores_after_alias_or_lost_ack_and_never_claims_probe_passed() {
        for alias in [false, true] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            let backup = mouse
                .prepare_layers(&before, vec![])
                .unwrap()
                .backup()
                .clone();
            mouse.transport.tag_last_write = true;
            mouse.transport.alias = alias;
            mouse.transport.lose_ack = !alias;
            let journal = trial_journal();
            let error = format!(
                "{:#}",
                mouse
                    .layer_write_probe(&backup, &journal, false)
                    .unwrap_err()
            );
            assert!(error.contains("restored and verified"), "{error}");
            assert_eq!(mouse.read_layers(None).unwrap(), before);
            assert_eq!(mouse.transport.writes.len(), 3);
            std::fs::remove_file(journal).unwrap();
        }
    }
    #[test]
    fn write_probe_stale_backups_and_unwritable_journal_prevent_mutations() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let backup = mouse
            .prepare_layers(&before, vec![])
            .unwrap()
            .backup()
            .clone();
        let journal = trial_journal();
        std::fs::write(&journal, b"existing").unwrap();
        assert!(mouse.layer_write_probe(&backup, &journal, false).is_err());
        std::fs::remove_file(&journal).unwrap();
        mouse.transport.secondary.get_mut(&(2, 0x34)).unwrap()[6] = 1;
        assert!(mouse.layer_write_probe(&backup, &journal, false).is_err());
        assert!(mouse.transport.writes.is_empty());
    }
    #[test]
    fn interrupted_probe_restore_never_reinstalls_b_and_rejects_unrelated_changes() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let backup = mouse
            .prepare_layers(&before, vec![])
            .unwrap()
            .backup()
            .clone();
        mouse.transport.tag_last_write = true;
        mouse.transport.echo_stuck = true;
        let journal = trial_journal();
        assert!(mouse.layer_write_probe(&backup, &journal, false).is_err());
        mouse.transport.echo_stuck = false;
        mouse.transport.secondary.get_mut(&(2, 0x34)).unwrap()[6] = 1;
        let writes = mouse.transport.writes.len();
        assert!(mouse.layer_write_probe(&backup, &journal, true).is_err());
        assert_eq!(mouse.transport.writes.len(), writes);
        mouse.transport.secondary.get_mut(&(2, 0x34)).unwrap()[6] = 0;
        mouse.layer_write_probe(&backup, &journal, true).unwrap();
        assert_eq!(mouse.read_layers(None).unwrap(), before);
        assert_eq!(mouse.transport.writes.len(), 5);
        std::fs::remove_file(journal).unwrap();
    }

    #[test]
    fn paired_reader_keeps_primary_and_ordinary_reads_strict_and_receiver_scope_unchanged() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        mouse.transport.normal_echo_one = true;
        assert!(mouse.read(None).is_err());
        let read = mouse.read_layers(None).unwrap();
        assert_eq!(read.normal_echoes[0].layer, 1);
        assert_eq!(read.hypershift.echoes[0].layer, 1);
        mouse.transport.slots.get_mut(&1).unwrap().product = 0xa8;
        assert!(mouse.read_layers(None).is_err());
        assert!(mouse.transport.writes.is_empty());
    }
    #[test]
    fn display_layer_view_still_requires_exact_freshness_before_save() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let view = mouse.preview_layers(None).unwrap();
        mouse.transport.normal_echo_one = true;
        assert!(mouse.prepare_layers(&view, layer_edits()).is_err());
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn paired_normal_echo_is_stale_state_and_missing_legacy_echoes_mean_strict_zero() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        mouse.transport.normal_echo_one = true;
        assert!(mouse.commit_layers(plan).is_err());
        assert!(mouse.transport.writes.is_empty());
        let mut legacy = serde_json::to_value(&before).unwrap();
        legacy.as_object_mut().unwrap().remove("normal_echoes");
        assert_eq!(
            serde_json::from_value::<layers::LayerReadback>(legacy).unwrap(),
            before
        );
    }
    #[test]
    fn rollback_preserves_a_preexisting_secondary_tag_after_lost_normal_ack() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let initial = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&initial, layer_edits()).unwrap();
        let before = mouse.commit_layers(plan).unwrap();
        assert_eq!(before.normal_echoes[0].layer, 1);
        let plan = mouse
            .prepare_layers(
                &before,
                vec![layer_transaction::LayerEdit {
                    layer: 0,
                    action: Button {
                        button: 1,
                        category: 2,
                        data: vec![0, 6],
                        raw_record: None,
                    },
                }],
            )
            .unwrap();
        mouse.transport.slots.get_mut(&1).unwrap().fail_once = Some(0x40);
        let error = format!("{:#}", mouse.commit_layers(plan).unwrap_err());
        assert!(error.contains("restored and verified"), "{error}");
        assert_eq!(mouse.read_layers(None).unwrap(), before);
    }

    #[test]
    fn unexpected_tag_during_save_is_rejected_without_retrying_the_new_action() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        mouse.transport.tag_last_write = false;
        assert!(mouse.commit_layers(plan).is_err());
        assert_eq!(mouse.read_layers(None).unwrap(), before);
        assert_eq!(
            mouse
                .transport
                .writes
                .iter()
                .filter(|(_, layer, id)| *layer == 1 && *id == 0x40)
                .count(),
            2
        );
    }

    #[test]
    fn paired_normal_factory_presets_are_position_scoped_and_secondary_functions_stay_rejected() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let edits: Vec<_> = crate::devices::naga_defaults()
            .controls
            .iter()
            .map(|c| layer_transaction::LayerEdit {
                layer: 0,
                action: Button {
                    button: c.button,
                    category: c.binding.category,
                    data: c.binding.data.clone(),
                    raw_record: None,
                },
            })
            .collect();
        assert!(mouse.prepare_layers(&before, edits).is_ok());
        for layer in [0, 1] {
            let control = &crate::devices::naga_defaults().controls[3];
            let bad = layer_transaction::LayerEdit {
                layer,
                action: Button {
                    button: if layer == 0 { 1 } else { 16 },
                    category: control.binding.category,
                    data: control.binding.data.clone(),
                    raw_record: None,
                },
            };
            assert!(mouse.prepare_layers(&before, vec![bad]).is_err());
        }
        assert!(mouse.transport.writes.is_empty());
    }
    #[test]
    fn legacy_normal_restore_uses_fresh_secondary_records_and_keeps_unknown_wire_bytes() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let original = mouse.read_layers(None).unwrap();
        let legacy = original.normal.clone();
        let plan = mouse.prepare_layers(&original, layer_edits()).unwrap();
        let active = mouse.commit_layers(plan).unwrap();
        let plan = mouse.prepare_layers_restore_normal(legacy.clone()).unwrap();
        let after = mouse.commit_layers(plan).unwrap();
        assert_eq!(after.normal, legacy);
        assert_eq!(after.hypershift, active.hypershift);
        assert_eq!(
            after.hypershift.controls[0].record().unwrap(),
            [14, 1, 104, 0, 20, 0, 0]
        );
        let mut old = legacy;
        old.controls.clear();
        old.buttons.reverse();
        let plan = mouse.prepare_layers_restore_normal(old).unwrap();
        assert_eq!(mouse.commit_layers(plan).unwrap(), after);
    }

    #[test]
    fn paired_activation_keeps_hypershift_and_echoes_across_slot_switches_without_mapping_writes() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let initial = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&initial, layer_edits()).unwrap();
        let before = mouse.commit_layers(plan).unwrap();
        let writes = mouse.transport.writes.len();
        let plan = mouse.prepare_layer_activation(&before, 2).unwrap();
        assert_eq!(plan.backup.slots.len(), 2);
        let after = mouse.commit_layer_activation(plan).unwrap();
        assert_eq!(after.normal.active, 2);
        assert_eq!(after.normal.slot, 2);
        let plan = mouse.prepare_layer_activation(&after, 1).unwrap();
        assert_eq!(mouse.commit_layer_activation(plan).unwrap(), before);
        assert_eq!(mouse.transport.writes.len(), writes);
    }
    #[test]
    fn paired_activation_stale_secondary_refuses_and_lost_ack_restores_every_slot() {
        for stale in [false, true] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            let plan = mouse.prepare_layer_activation(&before, 2).unwrap();
            if stale {
                mouse.transport.secondary.get_mut(&(2, 0x34)).unwrap()[6] ^= 1;
            } else {
                mouse.transport.slots.get_mut(&1).unwrap().fail_activations = 1;
            }
            let error = format!("{:#}", mouse.commit_layer_activation(plan).unwrap_err());
            if !stale {
                assert!(error.contains("restored and verified"), "{error}");
            } else {
                assert!(
                    !mouse
                        .transport
                        .operations
                        .iter()
                        .any(|(c, cmd, _)| (*c, *cmd) == (5, 4))
                );
            }
            assert!(mouse.transport.writes.is_empty());
            assert_eq!(mouse.read_layers(None).unwrap(), before);
        }
    }
    #[test]
    fn paired_creation_backs_up_secondary_and_refuses_configured_hypershift_before_allocation() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layer_creation(&before, 3).unwrap();
        assert!(plan.paired_backup.is_some());
        let after = mouse.commit_creation(plan).unwrap();
        assert!(after.slots.contains(&3));
        assert!(mouse.transport.writes.is_empty());
        let mut expected = before.clone();
        expected.normal.slots = after.slots;
        assert_eq!(mouse.read_layers(Some(1)).unwrap(), expected);
        let plan = mouse.prepare_layers(&expected, layer_edits()).unwrap();
        let configured = mouse.commit_layers(plan).unwrap();
        assert!(mouse.prepare_layer_creation(&configured, 4).is_err());
        assert!(
            !mouse
                .transport
                .operations
                .iter()
                .any(|(c, cmd, p)| (*c, *cmd) == (5, 2) && p[0] == 4)
        );
    }
    #[test]
    fn paired_creation_cleanup_never_claims_unchanged_if_an_original_secondary_bank_changed() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layer_creation(&before, 3).unwrap();
        mouse.transport.corrupt_secondary_on_allocate = true;
        let error = format!("{:#}", mouse.commit_creation(plan).unwrap_err());
        assert!(
            error.contains("original paired records could not be verified"),
            "{error}"
        );
        assert!(!mouse.transport.slots.contains_key(&3));
        assert!(mouse.transport.writes.is_empty());
    }

    fn layer_edits() -> Vec<layer_transaction::LayerEdit> {
        vec![
            layer_transaction::LayerEdit {
                layer: 1,
                action: Button {
                    button: 1,
                    category: 2,
                    data: vec![0, 5],
                    raw_record: None,
                },
            },
            layer_transaction::LayerEdit {
                layer: 0,
                action: Button {
                    button: 16,
                    category: 12,
                    data: vec![1],
                    raw_record: None,
                },
            },
        ]
    }
    #[test]
    fn paired_save_writes_secondary_then_trigger_and_restores_captured_raw_records() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        let backup = plan.backup().clone();
        assert_eq!(backup.slots.len(), 2);
        assert!(mouse.transport.writes.is_empty());
        mouse.commit_layers(plan).unwrap();
        assert_eq!(mouse.transport.writes, [(1, 1, 0x40), (1, 0, 0x60)]);
        let plan = mouse.prepare_layers_restore(&backup).unwrap();
        mouse.commit_layers(plan).unwrap();
        assert_eq!(mouse.read_layers(None).unwrap(), before);
        assert_eq!(
            mouse.transport.secondary[&(1, 0x40)],
            [2, 1, 0, 30, 0, 0, 0]
        );
        assert_eq!(
            mouse.transport.secondary[&(1, 0x34)],
            [14, 1, 104, 0, 20, 0, 0]
        );
    }
    #[test]
    fn paired_noop_preserves_noncanonical_wire_records_without_writes() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let edits = vec![layer_transaction::LayerEdit {
            layer: 1,
            action: Button {
                raw_record: None,
                ..before.hypershift.buttons[0].clone()
            },
        }];
        let plan = mouse.prepare_layers(&before, edits).unwrap();
        assert_eq!(mouse.commit_layers(plan).unwrap(), before);
        assert!(mouse.transport.writes.is_empty());
    }
    #[test]
    fn paired_commit_rejects_stale_raw_bytes_in_either_slot_or_bank() {
        for (slot, layer) in [(1, 0), (1, 1), (2, 0), (2, 1)] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
            if layer == 1 {
                mouse.transport.secondary.get_mut(&(slot, 0x34)).unwrap()[6] ^= 1;
            } else {
                mouse
                    .transport
                    .slots
                    .get_mut(&slot)
                    .unwrap()
                    .controls
                    .get_mut(&0x34)
                    .unwrap()
                    .data = vec![0, 5];
            }
            assert!(mouse.commit_layers(plan).is_err());
            assert!(mouse.transport.writes.is_empty());
        }
    }
    #[test]
    fn paired_lost_ack_and_unexpected_bank_alias_restore_both_banks_exactly() {
        for alias in [false, true] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
            mouse.transport.alias = alias;
            mouse.transport.lose_ack = !alias;
            let message = format!("{:#}", mouse.commit_layers(plan).unwrap_err());
            assert!(message.contains("restored and verified"), "{message}");
            assert_eq!(mouse.read_layers(None).unwrap(), before);
        }
    }
    #[test]
    fn paired_lost_trigger_ack_restores_already_written_secondary_and_trigger() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        mouse.transport.slots.get_mut(&1).unwrap().fail_once = Some(0x60);
        let error = format!("{:#}", mouse.commit_layers(plan).unwrap_err());
        assert!(error.contains("restored and verified"), "{error}");
        assert_eq!(mouse.read_layers(None).unwrap(), before);
        assert_eq!(
            mouse.transport.writes,
            [
                (1, 1, 0x40),
                (1, 0, 0x60),
                (1, 1, 0x40),
                (1, 0, 0x60),
                (1, 0, 0x40)
            ]
        );
    }

    #[test]
    fn paired_recovery_failure_keeps_explicit_incomplete_status() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        mouse.transport.lose_ack = true;
        mouse.transport.block_restore = true;
        let message = format!("{:#}", mouse.commit_layers(plan).unwrap_err());
        assert!(message.contains("rollback could not be verified"));
        assert!(!message.contains("restored and verified"));
    }
    #[test]
    fn paired_changed_actions_accept_reencoding_but_restore_requires_exact_bytes() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        let mut backup = plan.backup().clone();
        mouse.transport.reencode = true;
        mouse.commit_layers(plan).unwrap();
        let changed = mouse.read_layers(None).unwrap();
        // A canonical length-two backup cannot be restored by a setter that
        // always rewrites it as length one. Semantic equality must not suffice.
        backup.slots[0].state.hypershift.buttons[0].raw_record = None;
        let restore = mouse.prepare_layers_restore(&backup).unwrap();
        let message = format!("{:#}", mouse.commit_layers(restore).unwrap_err());
        assert!(message.contains("restored and verified"), "{message}");
        assert_eq!(mouse.read_layers(None).unwrap(), changed);
    }
    #[test]
    fn paired_edits_reject_primary_nested_trigger_unknown_action_and_receiver() {
        for (layer, button, category, data) in [
            (0, 0, 2, vec![0, 5]),
            (0, 17, 2, vec![0, 5]),
            (1, 1, 12, vec![1]),
            (1, 13, 14, vec![104]),
        ] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            assert!(
                mouse
                    .prepare_layers(
                        &before,
                        vec![layer_transaction::LayerEdit {
                            layer,
                            action: Button {
                                button,
                                category,
                                data,
                                raw_record: None
                            }
                        }]
                    )
                    .is_err()
            );
            assert!(mouse.transport.writes.is_empty());
        }
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        mouse.transport.slots.get_mut(&1).unwrap().product = 0xa8;
        let before = mouse.read_layers(None).unwrap();
        assert!(mouse.prepare_layers(&before, layer_edits()).is_err());
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn native_media_and_scroll_use_traced_wire_records_and_exact_paired_restore() {
        // Independent Device167 encoder findings (NATIVE_ACTIONS.md), not a
        // roundtrip generated from the editable action registry.
        for (layer, button, record) in [
            (0, 1, [10, 2, 0, 0xe9, 0, 0, 0]),
            (1, 1, [10, 2, 0, 0xea, 0, 0, 0]),
            (0, 13, [10, 2, 0, 0xe2, 0, 0, 0]),
            (1, 1, [10, 2, 0, 0xcd, 0, 0, 0]),
            (0, 15, [10, 2, 0, 0xb7, 0, 0, 0]),
            (1, 1, [10, 2, 0, 0xb5, 0, 0, 0]),
            (0, 12, [10, 2, 0, 0xb6, 0, 0, 0]),
            (0, 1, [1, 1, 9, 0, 0, 0, 0]),
            (1, 1, [1, 1, 10, 0, 0, 0, 0]),
            (0, 14, [1, 1, 0x68, 0, 0, 0, 0]),
            (1, 1, [1, 1, 0x69, 0, 0, 0, 0]),
        ] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            let action = Button::from_record(button, record).unwrap();
            let plan = mouse
                .prepare_layers(
                    &before,
                    vec![layer_transaction::LayerEdit {
                        layer,
                        action: action.clone(),
                    }],
                )
                .unwrap();
            let backup = plan.backup().clone();
            assert!(mouse.transport.writes.is_empty());
            let after = mouse.commit_layers(plan).unwrap();
            let entries = if layer == 0 {
                &after.normal.buttons
            } else {
                &after.hypershift.buttons
            };
            let controls = if layer == 0 {
                &after.normal.controls
            } else {
                &after.hypershift.controls
            };
            assert_eq!(
                entries
                    .iter()
                    .chain(controls)
                    .find(|b| b.button == button)
                    .unwrap(),
                &action
            );
            let id = control_id(button).unwrap();
            let write = mouse
                .transport
                .operations
                .iter()
                .find(|(class, cmd, p)| (*class, *cmd) == (2, 0x0c) && p[1] == id && p[2] == layer)
                .unwrap();
            assert_eq!(&write.2[3..], &record);
            let restore = mouse.prepare_layers_restore(&backup).unwrap();
            mouse.commit_layers(restore).unwrap();
            assert_eq!(mouse.read_layers(None).unwrap(), before);
        }
    }

    #[test]
    fn native_actions_reject_untraced_shapes_and_addresses_before_any_requests() {
        for (button, category, data) in [
            (0, 10, vec![0, 0xcd]),
            (17, 10, vec![0, 0xcd]),
            (0x30, 1, vec![9]),
            (1, 10, vec![0xcd]),
            (1, 10, vec![1, 0xcd]),
            (1, 10, vec![0xcd, 0]),
            (1, 10, vec![0, 0xcd, 0]),
            (1, 10, vec![0, 0xb0]),
            (1, 10, vec![0, 0xb1]),
            (1, 1, vec![6]),
            (1, 1, vec![7]),
            (1, 1, vec![9, 0]),
            (1, 6, vec![5, 3, 32, 3, 32]),
            (1, 7, vec![4]),
            (1, 14, vec![9, 0, 20]),
        ] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            mouse.transport.operations.clear();
            for layer in [0, 1] {
                let action = Button {
                    button,
                    category,
                    data: data.clone(),
                    raw_record: None,
                };
                assert!(
                    mouse
                        .prepare_layers(
                            &before,
                            vec![layer_transaction::LayerEdit { layer, action }]
                        )
                        .is_err()
                );
            }
            assert!(mouse.transport.operations.is_empty());
        }
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        for layer in [0, 1] {
            for button in 1..=16 {
                let action = Button::from_record(button, [10, 2, 0, 0xcd, 0, 0, 0]).unwrap();
                assert!(
                    mouse
                        .prepare_layers(
                            &before,
                            vec![layer_transaction::LayerEdit { layer, action }]
                        )
                        .is_ok()
                );
            }
        }
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn native_lost_ack_restores_captured_records_and_noop_keeps_unknown_padding() {
        for layer in [0, 1] {
            let mut mouse = Mouse {
                transport: BankFake::new(),
            };
            let before = mouse.read_layers(None).unwrap();
            let action = Button::from_record(1, [10, 2, 0, 0xcd, 0, 0, 0]).unwrap();
            let plan = mouse
                .prepare_layers(
                    &before,
                    vec![layer_transaction::LayerEdit { layer, action }],
                )
                .unwrap();
            if layer == 0 {
                mouse.transport.slots.get_mut(&1).unwrap().fail_once = Some(0x40);
            } else {
                mouse.transport.lose_ack = true;
            }
            let error = format!("{:#}", mouse.commit_layers(plan).unwrap_err());
            assert!(error.contains("restored and verified"), "{error}");
            assert_eq!(mouse.read_layers(None).unwrap(), before);
        }
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        mouse
            .transport
            .secondary
            .insert((1, 0x40), [10, 2, 0, 0xcd, 17, 23, 42]);
        let before = mouse.read_layers(None).unwrap();
        let action = Button::from_record(1, [10, 2, 0, 0xcd, 0, 0, 0]).unwrap();
        let plan = mouse
            .prepare_layers(
                &before,
                vec![layer_transaction::LayerEdit { layer: 1, action }],
            )
            .unwrap();
        mouse.commit_layers(plan).unwrap();
        assert!(mouse.transport.writes.is_empty());
        assert_eq!(mouse.read_layers(None).unwrap(), before);
    }
    #[test]
    fn paired_restore_rejects_diagnostic_envelope_and_different_device() {
        let mut mouse = Mouse {
            transport: BankFake::new(),
        };
        let before = mouse.read_layers(None).unwrap();
        assert!(
            serde_json::from_value::<layer_transaction::LayerBackup>(
                serde_json::to_value(&before).unwrap()
            )
            .is_err()
        );
        let plan = mouse.prepare_layers(&before, layer_edits()).unwrap();
        let mut backup = plan.backup().clone();
        backup.slots[0].state.normal.device.serial = "OTHER".into();
        assert!(mouse.prepare_layers_restore(&backup).is_err());
        assert!(mouse.transport.writes.is_empty());
    }

    struct LayerFake {
        normal: Fake,
        requests: Vec<(u8, u8, Vec<u8>)>,
        reads: std::collections::BTreeMap<u8, usize>,
        change_secondary: bool,
        reply_layer: u8,
        mirror_normal: bool,
        change_active: bool,
        change_plate: bool,
        initial_plate: u8,
        fail_secondary: bool,
        plate_reads: usize,
    }

    impl LayerFake {
        fn new() -> Self {
            Self {
                normal: Fake::captured_factory(),
                requests: vec![],
                reads: Default::default(),
                change_secondary: false,
                reply_layer: 1,
                mirror_normal: false,
                change_active: false,
                change_plate: false,
                initial_plate: 3,
                fail_secondary: false,
                plate_reads: 0,
            }
        }
    }

    impl Transport for LayerFake {
        fn identity(&self) -> Identity {
            self.normal.identity()
        }
        fn exchange(&mut self, class: u8, cmd: u8, p: &[u8], echo: usize) -> Result<Vec<u8>> {
            self.requests.push((class, cmd, p.to_vec()));
            match (class, cmd) {
                (0, 0xb9) => {
                    self.plate_reads += 1;
                    Ok(vec![if self.change_plate && self.plate_reads > 1 {
                        4
                    } else {
                        self.initial_plate
                    }])
                }
                (2, 0x8c) if p[2] == 1 => {
                    assert!(matches!(echo, 2 | 3));
                    assert_eq!(p.len(), 10);
                    assert_eq!(p[0], 1);
                    // Live inspection failed on primary wire 01, layer 1.
                    // Normal primary checks still work; secondary inspection
                    // must remain scoped to the permitted sixteen controls.
                    if p[1] <= 3 {
                        bail!("No matching reply to mouse command 02/8c");
                    }
                    if self.fail_secondary {
                        bail!("No matching reply to mouse command 02/8c");
                    }
                    let reads = self.reads.entry(p[1]).or_default();
                    *reads += 1;
                    // Synthetic secondary actions using the captured normal
                    // length-one keyboard encoding and traced trigger format.
                    let record = if self.mirror_normal {
                        self.normal
                            .controls
                            .get(&p[1])
                            .or_else(|| self.normal.buttons.get(&p[1]))
                            .unwrap()
                            .record()?
                    } else {
                        match p[1] {
                            0x40 => [0x7e, 2, 0xde, 0xad, 0x11, 0x22, 0x33],
                            0x41 => [2, 1, 0, 0x1f, 0, 0, 0],
                            0x34 => [0x0c, 1, 1, 0, 0, 0, 0],
                            _ => [0; 7],
                        }
                    };
                    let mut reply = p.to_vec();
                    reply[3..].copy_from_slice(&record);
                    if self.change_secondary && *reads > 1 && p[1] == 0x40 {
                        reply[9] ^= 1; // Same decoded action, different raw tail.
                    }
                    reply[2] = self.reply_layer;
                    if self.change_active {
                        self.normal.active = 2;
                    }
                    Ok(reply)
                }
                _ => self.normal.exchange(class, cmd, p, echo),
            }
        }
    }

    #[test]
    fn layer_export_preserves_normal_capture_and_unknown_secondary_wire_bytes_without_writes() {
        let original = Mouse {
            transport: Fake::captured_factory(),
        }
        .read(None)
        .unwrap();
        let mut mouse = Mouse {
            transport: LayerFake::new(),
        };
        let result = mouse.read_layers(None).unwrap();
        assert_eq!(result.normal, original);
        assert_eq!(result.hypershift.layer, 1);
        assert!(!result.hypershift.primary_inspected);
        assert_eq!(result.hypershift.buttons.len(), 12);
        assert_eq!(result.hypershift.controls.len(), 4);
        assert_eq!(result.hypershift.buttons[0].data, [0xde, 0xad]);
        assert_eq!(
            result.hypershift.buttons[0].raw_record,
            Some([0x7e, 2, 0xde, 0xad, 0x11, 0x22, 0x33])
        );
        assert_eq!(result.hypershift.buttons[1].data, [0, 0x1f]);
        assert!(result.hypershift.buttons[1].raw_record.is_some());
        let value = serde_json::to_value(&result).unwrap();
        assert_eq!(
            serde_json::from_value::<layers::LayerReadback>(value.clone()).unwrap(),
            result
        );
        assert!(serde_json::from_value::<Snapshot>(value).is_err());
        assert!(mouse.transport.requests.iter().all(|(class, cmd, _)| {
            matches!(
                (class, cmd),
                (0, 0x82 | 0x84 | 0xb9) | (5, 0x81 | 0x84) | (2, 0x8c)
            )
        }));
        assert_eq!(mouse.transport.reads.len(), 16);
        assert!(
            mouse
                .transport
                .reads
                .keys()
                .all(|id| { (0x40..=0x4b).contains(id) || [0x34, 0x35, 0x6d, 0x60].contains(id) })
        );
        assert!(mouse.transport.reads.values().all(|reads| *reads == 2));
        assert!(mouse.transport.normal.writes.is_empty());
    }

    #[test]
    fn layer_inspection_rejects_wrong_bank_echo_and_changes_to_raw_state_active_slot_or_plate() {
        for failure in 0..4 {
            let mut transport = LayerFake::new();
            transport.reply_layer = if failure == 0 { 2 } else { 1 };
            transport.change_secondary = failure == 1;
            transport.change_active = failure == 2;
            transport.change_plate = failure == 3;
            let mut mouse = Mouse { transport };
            let error = format!("{:#}", mouse.read_layers(None).unwrap_err());
            assert!(error.contains(match failure {
                0 => "Unexpected secondary layer echo",
                1 => "Hypershift records changed",
                2 => "Normal bindings or device state changed",
                _ => "Faceplate changed",
            }));
            assert!(mouse.transport.normal.writes.is_empty());
        }
    }

    #[test]
    fn layer_inspection_rejects_uninitialized_slots_before_secondary_reads() {
        let mut mouse = Mouse {
            transport: LayerFake::new(),
        };
        assert!(mouse.read_layers(Some(3)).is_err());
        assert!(mouse.transport.reads.is_empty());
        assert!(mouse.transport.normal.writes.is_empty());
    }

    #[test]
    fn layer_getter_failures_identify_bank_slot_and_control_without_writes() {
        let mut transport = LayerFake::new();
        transport.fail_secondary = true;
        let mut mouse = Mouse { transport };
        let error = format!("{:#}", mouse.read_layers(None).unwrap_err());
        assert!(error.contains("First Hypershift-bank read"));
        assert!(error.contains("slot 1, button 1 (wire 0x40), layer 1"));
        assert!(error.contains("No matching reply to mouse command 02/8c"));
        assert!(mouse.transport.normal.writes.is_empty());
    }

    #[test]
    fn layer_inspection_rejects_other_plates_before_reading_mapping_banks() {
        for initial_plate in [0, 1, 4, 255] {
            let mut transport = LayerFake::new();
            transport.initial_plate = initial_plate;
            let mut mouse = Mouse { transport };
            assert!(mouse.read_layers(None).is_err());
            assert_eq!(mouse.transport.requests.len(), 1);
            assert!(mouse.transport.normal.writes.is_empty());
        }
    }

    #[test]
    fn v2_pro_zero_echo_is_preserved_and_forensic_envelopes_stay_unverified() {
        for mirror_normal in [true, false] {
            let mut transport = LayerFake::new();
            transport.reply_layer = 0;
            transport.mirror_normal = mirror_normal;
            let mut mouse = Mouse { transport };
            // General mapping readers keep all three echo checks. Only the
            // V2 Pro layer-specific reader applies the documented zero quirk.
            assert!(
                mouse
                    .get_layer_button(1, 0x40, 1, MappingLayer::Hypershift)
                    .is_err()
            );
            let selected = mouse.read_layers(Some(1)).unwrap();
            assert!(selected.hypershift.echoes.iter().all(|e| e.layer == 0));
            let probe = mouse.probe_layer_replies(Some(1)).unwrap();
            assert!(!probe.secondary_verified);
            assert_eq!(probe.kind, "unverified_layer_replies");
            assert_eq!(probe.replies.len(), 16);
            assert!(
                probe
                    .replies
                    .iter()
                    .all(|r| r.requested_layer == 1 && r.echoed_layer == 0)
            );
            assert_eq!(
                probe.replies.iter().all(|r| r.matches_normal_wire),
                mirror_normal
            );
            let value = serde_json::to_value(&probe).unwrap();
            assert!(serde_json::from_value::<Snapshot>(value.clone()).is_err());
            assert!(serde_json::from_value::<layers::LayerReadback>(value.clone()).is_err());
            assert_eq!(
                serde_json::from_value::<layers::LayerReplyProbe>(value).unwrap(),
                probe
            );
            assert!(mouse.transport.normal.writes.is_empty());
            assert!(mouse.transport.requests.iter().all(|(c, cmd, _)| matches!(
                (c, cmd),
                (0, 0x82 | 0x84 | 0xb9) | (5, 0x81 | 0x84) | (2, 0x8c)
            )));
        }
    }

    #[test]
    fn reply_probes_still_reject_unstable_bytes_and_changed_normal_state_or_plate() {
        for failure in 0..3 {
            let mut transport = LayerFake::new();
            transport.reply_layer = 0;
            transport.change_secondary = failure == 0;
            transport.change_active = failure == 1;
            transport.change_plate = failure == 2;
            let mut mouse = Mouse { transport };
            let error = format!("{:#}", mouse.probe_layer_replies(Some(1)).unwrap_err());
            assert!(error.contains(match failure {
                0 => "Diagnostic replies changed",
                1 => "Normal state changed",
                _ => "Faceplate changed",
            }));
            assert!(mouse.transport.normal.writes.is_empty());
        }
    }

    #[test]
    fn captured_layer_replies_distinguish_wire_only_changes_from_different_actions() {
        // Sanitized records from the user's wired layer-1 request capture.
        for (logical, normal, selected, same_action) in [
            (1, [2, 2, 0, 0x1e, 0, 0, 0], [2, 1, 0, 0x1e, 0, 0, 0], true),
            (2, [2, 2, 0, 0x1f, 0, 0, 0], [2, 1, 0, 0x1f, 0, 0, 0], true),
            (
                13,
                [2, 2, 0, 0x68, 0, 0, 0],
                [14, 1, 0x68, 0, 20, 0, 0],
                false,
            ),
            (
                14,
                [2, 2, 0, 0x69, 0, 0, 0],
                [14, 1, 0x69, 0, 20, 0, 0],
                false,
            ),
        ] {
            let before = Button::from_record(logical, normal).unwrap();
            let after = Button::from_record(logical, selected).unwrap();
            assert_eq!(before.same_action(&after), same_action);
            assert_ne!(before.record().unwrap(), after.record().unwrap());
            assert_eq!(after.record().unwrap(), selected);
            assert!(after.raw_record.is_some());
        }
    }

    #[test]
    fn zero_layer_echo_quirk_is_not_applied_to_other_products() {
        let mut transport = LayerFake::new();
        transport.normal.product = 0x91;
        transport.reply_layer = 0;
        let mut mouse = Mouse { transport };
        let error = format!("{:#}", mouse.read_layers(Some(1)).unwrap_err());
        assert!(error.contains("restricted to Naga V2 Pro"));
        assert!(mouse.transport.reads.is_empty());
        assert!(mouse.transport.normal.writes.is_empty());
    }

    #[test]
    fn creation_keeps_existing_active_slot_and_factory_records_without_mapping_writes() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        let plan = mouse.prepare_creation(&before, 3).unwrap();
        assert!(!mouse.transport.requests.contains(&(5, 2)));
        assert_eq!(plan.backup.snapshots.len(), 2);
        let created = mouse.commit_creation(plan).unwrap();
        assert_eq!((created.slot, created.active), (3, 1));
        assert_eq!(created.slots, vec![1, 2, 3]);
        assert_eq!(created.buttons, before.buttons);
        let mutations: Vec<_> = mouse
            .transport
            .requests
            .iter()
            .copied()
            .filter(|(_, cmd)| *cmd < 0x80)
            .collect();
        assert_eq!(mutations, vec![(5, 2)]);
    }

    #[test]
    fn creation_refuses_existing_slots_and_rechecks_state_after_preparation() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        assert!(mouse.prepare_creation(&before, 2).is_err());
        assert!(mouse.prepare_creation(&before, 6).is_err());
        let plan = mouse.prepare_creation(&before, 3).unwrap();
        mouse.transport.active = 2;
        assert!(mouse.commit_creation(plan).is_err());
        assert!(!mouse.transport.requests.contains(&(5, 2)));
    }

    #[test]
    fn creation_rejects_receiver_and_driver_mode_without_writes() {
        for receiver in [true, false] {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            if receiver {
                mouse.transport.product = 0xa8;
            } else {
                mouse.transport.mode = vec![3, 0];
            }
            let before = mouse.read(None).unwrap();
            assert!(mouse.prepare_creation(&before, 3).is_err());
            assert!(!mouse.transport.requests.iter().any(|(_, cmd)| *cmd < 0x80));
        }
    }

    #[test]
    fn creation_failure_cleans_up_without_fixing_primary_or_retrying_allocation() {
        for case in 0..3 {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            let before = mouse.read(None).unwrap();
            let plan = mouse.prepare_creation(&before, 3).unwrap();
            match case {
                0 => mouse.transport.allocation_fails = true,
                1 => mouse.transport.blank_new_primary = true,
                _ => mouse.transport.allocation_activates = true,
            }
            assert!(mouse.commit_creation(plan).is_err());
            assert_eq!(mouse.read(None).unwrap(), before);
            assert_eq!(
                mouse
                    .transport
                    .requests
                    .iter()
                    .filter(|r| **r == (5, 2))
                    .count(),
                1
            );
            assert!(mouse.transport.wire_writes.is_empty());
        }
    }

    #[test]
    fn creation_failed_cleanup_is_reported_and_not_retried() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        let plan = mouse.prepare_creation(&before, 3).unwrap();
        mouse.transport.blank_new_primary = true;
        mouse.transport.deletion_fails = true;
        let error = mouse.commit_creation(plan).unwrap_err();
        assert!(error.to_string().contains("cleanup incomplete"));
        assert_eq!(
            mouse
                .transport
                .requests
                .iter()
                .filter(|r| **r == (5, 3))
                .count(),
            1
        );
    }

    #[test]
    fn activation_only_switches_active_slot_preserving_every_mapping_record() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        let plan = mouse.prepare_activation(&before, 2).unwrap();
        assert!(!mouse.transport.requests.contains(&(5, 4)));
        let after = mouse.commit_activation(plan).unwrap();
        assert_eq!((after.slot, after.active), (2, 2));
        assert_eq!(after.buttons, before.buttons);
        assert_eq!(after.primary, before.primary);
        let mutations: Vec<_> = mouse
            .transport
            .requests
            .iter()
            .copied()
            .filter(|(_, c)| *c < 0x80)
            .collect();
        assert_eq!(mutations, vec![(5, 4)]);
    }

    #[test]
    fn activation_rejects_uninitialized_active_unsafe_and_stale_targets() {
        for case in 0..5 {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            if case == 2 {
                mouse.transport.mode = vec![3, 0];
            }
            if case == 3 {
                // Make slot 3 initialized but its primary click unsafe.
                mouse.transport.inventory.push(3);
                mouse.transport.blank_new_primary = true;
            }
            let before = mouse.read(None).unwrap();
            if case == 4 {
                let plan = mouse.prepare_activation(&before, 2).unwrap();
                mouse.transport.active = 2;
                assert!(mouse.commit_activation(plan).is_err());
            } else {
                let target = match case {
                    0 | 3 => 3,
                    1 => 1,
                    _ => 2,
                };
                assert!(mouse.prepare_activation(&before, target).is_err());
            }
            assert!(!mouse.transport.requests.iter().any(|(_, c)| *c < 0x80));
        }
    }

    #[test]
    fn activation_lost_ack_restores_previous_slot_and_reports_failed_rollback() {
        for failures in [1, 2] {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            let before = mouse.read(None).unwrap();
            let plan = mouse.prepare_activation(&before, 2).unwrap();
            mouse.transport.fail_activations = failures;
            let error = mouse.commit_activation(plan).unwrap_err().to_string();
            if failures == 1 {
                assert!(error.contains("Previous active slot restored"));
                assert_eq!(mouse.read(None).unwrap(), before);
            } else {
                assert!(error.contains("could not be verified"));
            }
            assert!(mouse.transport.wire_writes.is_empty());
            assert_eq!(
                mouse
                    .transport
                    .requests
                    .iter()
                    .filter(|r| **r == (5, 4))
                    .count(),
                2
            );
        }
    }

    #[test]
    fn captured_wheel_controls_survive_grid_save_and_explicit_backup_restore() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        for (button, id, category, data) in [(13, 0x34, 1, 4), (14, 0x35, 1, 5), (15, 0x6d, 18, 4)]
        {
            mouse.transport.controls.insert(
                id,
                Button {
                    button,
                    category,
                    data: vec![data],
                    raw_record: None,
                },
            );
        }
        let before = mouse.read(None).unwrap();
        let mut grid = before.buttons.clone();
        grid[0] = Button {
            button: 1,
            category: 2,
            data: vec![0, 5],
            raw_record: None,
        };
        let plan = mouse.prepare_controls(&before, grid, vec![]).unwrap();
        assert_eq!(mouse.commit(plan).unwrap().controls, before.controls);
        assert_eq!(mouse.transport.writes, vec![0x40]);
        // Restore the actual captured firmware action without treating its
        // unimplemented category as a user-editable action.
        mouse.transport.controls.get_mut(&0x6d).unwrap().category = 0;
        mouse
            .transport
            .controls
            .get_mut(&0x6d)
            .unwrap()
            .data
            .clear();
        let plan = mouse.prepare_restore(before.clone()).unwrap();
        assert_eq!(mouse.commit(plan).unwrap().controls, before.controls);
        assert_eq!(
            mouse.transport.controls[&0x6d].record().unwrap(),
            [18, 1, 4, 0, 0, 0, 0]
        );
    }

    #[test]
    fn wheel_controls_have_explicit_addresses_and_preserve_other_records() {
        for (button, id) in [(13, 0x34), (14, 0x35), (15, 0x6d)] {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            let before = mouse.read(None).unwrap();
            let desired = Button {
                button,
                category: 2,
                data: vec![0, 5],
                raw_record: None,
            };
            let plan = mouse
                .prepare_controls(&before, before.buttons.clone(), vec![desired.clone()])
                .unwrap();
            let after = mouse.commit(plan).unwrap();
            assert_eq!(mouse.transport.writes, vec![id]);
            assert_eq!(after.buttons, before.buttons);
            assert_eq!(after.primary, before.primary);
            assert_eq!(
                after.controls.iter().find(|b| b.button == button).unwrap(),
                &desired
            );
            for original in before.controls.iter().filter(|b| b.button != button) {
                assert!(after.controls.contains(original));
            }
        }
        for button in [0, 17, 0x34, 0xff] {
            assert!(control_id(button).is_err());
        }
    }

    #[test]
    fn lost_wheel_write_ack_restores_unknown_raw_control_record_exactly() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let raw = [0x91, 1, 2, 3, 4, 5, 6];
        mouse
            .transport
            .controls
            .insert(0x6d, Button::from_record(15, raw).unwrap());
        let before = mouse.read(None).unwrap();
        let desired = Button {
            button: 15,
            category: 2,
            data: vec![0, 5],
            raw_record: None,
        };
        let plan = mouse
            .prepare_controls(&before, before.buttons.clone(), vec![desired])
            .unwrap();
        mouse.transport.fail_once = Some(0x6d);
        assert!(mouse.commit(plan).is_err());
        assert_eq!(mouse.read(None).unwrap(), before);
        assert_eq!(mouse.transport.writes, vec![0x6d, 0x6d]);
        assert_eq!(mouse.transport.wire_writes.last().unwrap().1, raw);
    }

    #[test]
    fn legacy_backups_preserve_controls_and_new_backups_restore_them() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let backup = mouse.read(None).unwrap();
        let mut legacy = serde_json::to_value(&backup).unwrap();
        legacy.as_object_mut().unwrap().remove("controls");
        let legacy: Snapshot = serde_json::from_value(legacy).unwrap();
        mouse.transport.controls.get_mut(&0x34).unwrap().category = 0x90;
        let changed = mouse.read(None).unwrap().controls;
        let plan = mouse.prepare_restore(legacy).unwrap();
        assert_eq!(mouse.commit(plan).unwrap().controls, changed);
        let plan = mouse.prepare_restore(backup.clone()).unwrap();
        assert_eq!(mouse.commit(plan).unwrap().controls, backup.controls);
    }

    #[test]
    fn factory_control_presets_are_scoped_and_rollback_restores_originals() {
        let defaults: Vec<_> = [(13, 1, 0x68), (14, 1, 0x69), (15, 18, 4), (16, 6, 6)]
            .into_iter()
            .map(|(button, category, data)| Button {
                button,
                category,
                data: vec![data],
                raw_record: None,
            })
            .collect();
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        let plan = mouse
            .prepare_controls(&before, before.buttons.clone(), defaults.clone())
            .unwrap();
        mouse.transport.fail_once = Some(0x6d);
        assert!(mouse.commit(plan).is_err());
        assert_eq!(mouse.read(None).unwrap(), before);
        mouse.transport.writes.clear();
        let plan = mouse
            .prepare_controls(&before, before.buttons.clone(), defaults)
            .unwrap();
        let after = mouse.commit(plan).unwrap();
        assert_eq!(
            after
                .controls
                .iter()
                .map(|b| (b.category, b.data.clone()))
                .collect::<Vec<_>>(),
            vec![
                (1, vec![0x68]),
                (1, vec![0x69]),
                (18, vec![4]),
                (6, vec![6])
            ]
        );
        assert_eq!(mouse.transport.writes, vec![0x34, 0x35, 0x6d, 0x60]);
        for (button, category, data) in [
            (13, 18, 4),
            (15, 18, 5),
            (14, 1, 0x68),
            (13, 1, 9),
            (14, 1, 10),
            (16, 6, 7),
            (13, 6, 6),
        ] {
            let bad = Button {
                button,
                category,
                data: vec![data],
                raw_record: None,
            };
            assert!(
                mouse
                    .prepare_controls(&after, after.buttons.clone(), vec![bad])
                    .is_err()
            );
        }
    }

    #[test]
    fn dpi_button_changes_only_its_record_and_legacy_backups_preserve_it() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let raw = [0x90, 1, 7, 8, 9, 10, 11];
        mouse
            .transport
            .controls
            .insert(0x60, Button::from_record(16, raw).unwrap());
        let before = mouse.read(None).unwrap();
        let key = Button {
            button: 16,
            category: 2,
            data: vec![0, 5],
            raw_record: None,
        };
        let plan = mouse
            .prepare_controls(&before, before.buttons.clone(), vec![key.clone()])
            .unwrap();
        mouse.transport.fail_once = Some(0x60);
        assert!(mouse.commit(plan).is_err());
        assert_eq!(mouse.read(None).unwrap(), before);
        mouse.transport.writes.clear();
        let plan = mouse
            .prepare_controls(&before, before.buttons.clone(), vec![key.clone()])
            .unwrap();
        let after = mouse.commit(plan).unwrap();
        assert_eq!(mouse.transport.writes, vec![0x60]);
        assert_eq!(after.controls.last().unwrap(), &key);
        assert_eq!(after.controls[..3], before.controls[..3]);
        assert_eq!(after.primary, before.primary);
        assert_eq!(after.buttons, before.buttons);
        let mut legacy = before.clone();
        legacy.controls.retain(|c| c.button != 16);
        let plan = mouse.prepare_restore(legacy).unwrap();
        assert_eq!(mouse.commit(plan).unwrap().controls.last().unwrap(), &key);
        let plan = mouse.prepare_restore(before.clone()).unwrap();
        assert_eq!(mouse.commit(plan).unwrap(), before);
        assert!(
            !mouse
                .transport
                .requests
                .iter()
                .any(|(class, cmd)| *class == 4 && *cmd < 0x80)
        );
    }

    fn trial_plan(mouse: &mut Mouse<Fake>) -> slot_trial::Plan {
        slot_trial::Plan {
            format: 1,
            target: 3,
            snapshots: vec![mouse.read(Some(1)).unwrap(), mouse.read(Some(2)).unwrap()],
        }
    }

    fn trial_journal() -> std::path::PathBuf {
        static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
        std::env::temp_dir().join(format!(
            "nagalibre-trial-{}-{}.jsonl",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ))
    }

    #[test]
    fn slot_trial_removes_only_new_slot_without_mapping_or_mode_writes() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let plan = trial_plan(&mut mouse);
        let journal = trial_journal();
        mouse.slot_trial(&plan, &journal).unwrap();
        let text = std::fs::read_to_string(&journal).unwrap();
        std::fs::remove_file(journal).unwrap();
        assert!(text.contains("defaults_read") && text.contains("finished"));
        assert_eq!(mouse.transport.inventory, vec![5, 1, 2]);
        let mutations: Vec<_> = mouse
            .transport
            .requests
            .iter()
            .copied()
            .filter(|(_, command)| *command < 0x80)
            .collect();
        assert_eq!(mutations, vec![(5, 2), (5, 3)]);
    }

    #[test]
    fn slot_trial_cleans_up_lost_allocation_ack_and_unexpected_activation() {
        for activate in [false, true] {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            let plan = trial_plan(&mut mouse);
            mouse.transport.allocation_fails = !activate;
            mouse.transport.allocation_activates = activate;
            let journal = trial_journal();
            assert!(mouse.slot_trial(&plan, &journal).is_err());
            std::fs::remove_file(journal).unwrap();
            assert_eq!(mouse.transport.inventory, vec![5, 1, 2]);
            assert_eq!(mouse.transport.active, 1);
            assert_eq!(
                mouse
                    .transport
                    .requests
                    .iter()
                    .filter(|r| **r == (5, 2))
                    .count(),
                1
            );
            assert!(mouse.transport.wire_writes.is_empty());
        }
    }

    #[test]
    fn slot_trial_rejects_stale_incomplete_existing_and_undurable_plans() {
        for case in 0..4 {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            let mut plan = trial_plan(&mut mouse);
            let journal = trial_journal();
            match case {
                0 => plan.target = 2,
                1 => {
                    plan.snapshots.pop();
                }
                2 => mouse.transport.active = 2,
                _ => std::fs::write(&journal, b"existing").unwrap(),
            }
            assert!(mouse.slot_trial(&plan, &journal).is_err());
            let _ = std::fs::remove_file(journal);
            assert!(!mouse.transport.requests.contains(&(5, 2)));
        }
    }

    #[test]
    fn slot_trial_reports_failed_cleanup_without_retry_or_success_claim() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let plan = trial_plan(&mut mouse);
        mouse.transport.deletion_fails = true;
        let journal = trial_journal();
        let error = mouse.slot_trial(&plan, &journal).unwrap_err();
        assert!(error.to_string().contains("cleanup"));
        let text = std::fs::read_to_string(&journal).unwrap();
        std::fs::remove_file(journal).unwrap();
        assert!(text.contains("Temporary slot remains"));
        assert_eq!(
            mouse
                .transport
                .requests
                .iter()
                .filter(|r| **r == (5, 3))
                .count(),
            1
        );
    }

    #[test]
    fn unchanged_gui_factory_save_preserves_captured_records_without_button_writes() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        let plan = mouse.prepare(&before, Fake::gui_factory()).unwrap();
        assert_eq!(plan.desired, before.buttons);
        assert_eq!(mouse.commit(plan).unwrap(), before);
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn gui_change_to_b_writes_only_first_button_and_preserves_other_wire_records() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let before = mouse.read(None).unwrap();
        let mut desired = Fake::gui_factory();
        desired[0].data = vec![0, 5];
        let plan = mouse.prepare(&before, desired).unwrap();
        let after = mouse.commit(plan).unwrap();
        assert_eq!(mouse.transport.writes, vec![0x40]);
        assert_eq!(
            mouse.transport.wire_writes,
            vec![(0x40, [2, 2, 0, 5, 0, 0, 0])]
        );
        assert_eq!(after.buttons[0].data, vec![0, 5]);
        assert_eq!(after.buttons[1..], before.buttons[1..]);
        assert_eq!(after.primary, before.primary);
    }

    #[test]
    fn failed_gui_save_restores_captured_and_unknown_records_byte_for_byte() {
        for unknown in [false, true] {
            let mut mouse = Mouse {
                transport: Fake::captured_factory(),
            };
            if unknown {
                mouse.transport.buttons.insert(
                    0x42,
                    Button::from_record(3, [0x12, 1, 8, 7, 6, 5, 4]).unwrap(),
                );
            }
            let before = mouse.read(None).unwrap();
            let mut desired = Fake::gui_factory();
            desired[0].data = vec![0, 5];
            desired[2].data = vec![0, 6];
            let plan = mouse.prepare(&before, desired).unwrap();
            mouse.transport.fail_once = Some(0x42);
            assert!(
                mouse
                    .commit(plan)
                    .unwrap_err()
                    .to_string()
                    .contains("were restored")
            );
            assert_eq!(mouse.transport.writes, vec![0x40, 0x42, 0x42, 0x40]);
            assert_eq!(
                mouse.transport.wire_writes[2],
                (0x42, before.buttons[2].record().unwrap())
            );
            assert_eq!(
                mouse.transport.wire_writes[3],
                (0x40, before.buttons[0].record().unwrap())
            );
            assert_eq!(mouse.read(None).unwrap(), before);
        }
    }

    #[test]
    fn explicit_restore_restores_original_encoding_even_when_actions_match() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let backup = mouse.read(None).unwrap();
        for b in mouse.transport.buttons.values_mut() {
            b.raw_record = None;
        }
        let plan = mouse.prepare_restore(backup.clone()).unwrap();
        assert_eq!(mouse.commit(plan).unwrap(), backup);
        assert_eq!(mouse.transport.writes, (0x42..=0x4b).collect::<Vec<_>>());
        for (id, wire) in &mouse.transport.wire_writes {
            assert_eq!(
                *wire,
                backup.buttons[usize::from(*id - 0x40)].record().unwrap()
            );
        }
    }

    #[test]
    fn explicit_restore_preserves_unknown_action_and_trailing_bytes() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let raw = [0x12, 1, 8, 7, 6, 5, 4];
        mouse
            .transport
            .buttons
            .insert(0x42, Button::from_record(3, raw).unwrap());
        let backup = mouse.read(None).unwrap();
        mouse.transport.buttons.insert(
            0x42,
            Button::from_record(3, [0x12, 1, 8, 0, 0, 0, 0]).unwrap(),
        );
        let plan = mouse.prepare_restore(backup.clone()).unwrap();
        assert_eq!(mouse.commit(plan).unwrap(), backup);
        assert_eq!(mouse.transport.wire_writes, vec![(0x42, raw)]);
    }

    #[test]
    fn gui_verifies_changed_actions_but_explicit_restore_requires_exact_encoding() {
        let mut mouse = Mouse {
            transport: Fake::captured_factory(),
        };
        let backup = mouse.read(None).unwrap();
        let mut desired = Fake::gui_factory();
        desired[0].data = vec![0, 5];
        let plan = mouse.prepare(&backup, desired).unwrap();
        mouse.transport.reencode_once = true;
        let after = mouse.commit(plan).unwrap();
        assert_eq!(after.buttons[0].data, vec![0, 5]);
        assert_eq!(after.buttons[0].record().unwrap(), [2, 1, 0, 5, 0, 0, 0]);
        assert_eq!(mouse.transport.writes, vec![0x40]);
        let plan = mouse.prepare_restore(backup).unwrap();
        mouse.transport.reencode_once = true;
        let error = mouse.commit(plan).unwrap_err().to_string();
        assert!(error.contains("Read-back mismatch"), "{error}");
        assert_eq!(mouse.read(None).unwrap(), after);
    }

    #[test]
    fn captured_keyboard_records_decode_all_factory_keys_and_preserve_wire_bytes() {
        let usages = [
            0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2d, 0x2e,
        ];
        for (index, usage) in usages.into_iter().enumerate() {
            let length = if index < 2 { 2 } else { 1 };
            let raw = [2, length, 0, usage, 0, 0, 0];
            let button = Button::from_record(index as u8 + 1, raw).unwrap();
            assert_eq!(button.data, vec![0, usage]);
            assert_eq!(button.raw_record.is_some(), length == 1);
            assert_eq!(button.record().unwrap(), raw);
            let json = serde_json::to_string(&button).unwrap();
            let restored: Button = serde_json::from_str(&json).unwrap();
            assert_eq!(restored.record().unwrap(), raw);
        }
        let legacy: Button =
            serde_json::from_str(r#"{"button":1,"category":2,"data":[0,30]}"#).unwrap();
        assert_eq!(legacy.raw_record, None);
        assert_eq!(legacy.record().unwrap(), [2, 2, 0, 30, 0, 0, 0]);
        let unknown = [0x12, 1, 8, 7, 6, 5, 4];
        assert_eq!(
            Button::from_record(1, unknown).unwrap().record().unwrap(),
            unknown
        );
        assert!(Button::from_record(1, [2, 6, 0, 0, 0, 0, 0]).is_err());
    }

    #[test]
    fn short_keyboard_records_survive_backup_restore_and_failed_save_rollback() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let raw = [2, 1, 0, 0x20, 0, 0, 0];
        mouse
            .transport
            .buttons
            .insert(0x42, Button::from_record(3, raw).unwrap());
        let before = mouse.read(None).unwrap();
        let backup: Snapshot =
            serde_json::from_str(&serde_json::to_string(&before).unwrap()).unwrap();
        let mut desired = before.buttons.clone();
        desired[2].data = vec![0, 5];
        desired[2].raw_record = None;
        let plan = mouse.prepare(&before, desired).unwrap();
        mouse.transport.fail_once = Some(0x42);
        assert!(
            mouse
                .commit(plan)
                .unwrap_err()
                .to_string()
                .contains("were restored")
        );
        assert_eq!(mouse.read(None).unwrap(), before);
        // Restore must carry the original length byte and trailing usage too.
        mouse.transport.buttons.get_mut(&0x42).unwrap().raw_record = None;
        let plan = mouse.prepare_restore(backup).unwrap();
        mouse.commit(plan).unwrap();
        assert_eq!(mouse.transport.buttons[&0x42].record().unwrap(), raw);
    }

    #[test]
    fn inconsistent_raw_backup_is_rejected_before_writes() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let mut backup = mouse.read(None).unwrap();
        backup.buttons[0].raw_record = Some([2, 1, 0, 5, 0, 0, 0]);
        assert!(mouse.prepare_restore(backup).is_err());
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn compact_hardware_inventory_reads_both_initialized_slots_without_writes() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        mouse.transport.inventory = vec![5, 1, 2];
        let snapshot = mouse.read(None).unwrap();
        assert_eq!(snapshot.slot_capacity, Some(5));
        assert_eq!(snapshot.slots, vec![1, 2]);
        assert_eq!(snapshot.slot, 1);
        assert_eq!(mouse.read(Some(2)).unwrap().slot, 2);
        assert!(mouse.read(Some(3)).is_err());
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn slot_inventory_reports_capacity_separately_and_only_uses_getters() {
        for (payload, capacity, initialized, active) in [
            (vec![5, 1, 2], 5, vec![1, 2], 1),
            (vec![5, 1, 4, 0, 0, 0], 5, vec![1, 4], 4),
            (vec![2, 1, 2], 2, vec![1, 2], 2),
            (vec![1, 1, 0, 0, 0, 0], 1, vec![1], 1),
            (vec![3, 0, 0, 0, 0, 0], 3, vec![], 0),
        ] {
            let mut mouse = Mouse {
                transport: Fake::new(),
            };
            mouse.transport.inventory = payload;
            mouse.transport.active = active;
            assert_eq!(
                mouse.slot_inventory().unwrap(),
                SlotInventory {
                    capacity,
                    initialized,
                    active
                }
            );
            assert_eq!(mouse.transport.requests, vec![(5, 0x81), (5, 0x84)]);
            assert!(mouse.transport.writes.is_empty());
        }
        for payload in [vec![2, 3], vec![5, 1, 0, 0, 0, 0, 0]] {
            let mut mouse = Mouse {
                transport: Fake::new(),
            };
            mouse.transport.inventory = payload;
            assert!(mouse.slot_inventory().is_err());
        }
    }

    #[test]
    fn capacity_changes_invalidate_saves_and_legacy_backups_still_restore() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        let before = mouse.read(None).unwrap();
        mouse.transport.inventory = vec![4, 1, 2];
        assert!(mouse.prepare(&before, before.buttons.clone()).is_err());
        assert!(mouse.transport.writes.is_empty());
        mouse.transport.inventory = vec![5, 1, 2];
        let mut legacy = serde_json::to_value(&before).unwrap();
        legacy.as_object_mut().unwrap().remove("slot_capacity");
        let legacy: Snapshot = serde_json::from_value(legacy).unwrap();
        assert_eq!(legacy.slot_capacity, None);
        let plan = mouse.prepare_restore(legacy).unwrap();
        let after = mouse.commit(plan).unwrap();
        assert_eq!(after.slot_capacity, Some(5));
        assert!(mouse.transport.writes.is_empty());
    }

    #[test]
    fn invalid_or_empty_inventories_fail_without_writes() {
        let mut mouse = Mouse {
            transport: Fake::new(),
        };
        for inventory in [
            vec![],
            vec![6, 1],
            vec![1, 1, 2],
            vec![5, 1, 1],
            vec![5, 6],
            vec![5, 0],
            vec![5],
            vec![0],
            vec![0, 1],
        ] {
            mouse.transport.inventory = inventory;
            assert!(mouse.read(None).is_err());
            assert!(mouse.transport.writes.is_empty());
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
