//! Read-only normal/Hypershift inspection with model-scoped echo handling.
use super::*;

/// A diagnostic export, not a mapping backup accepted by the restoration writer.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerReadback {
    pub format: u8,
    pub normal: Snapshot,
    /// Missing in early read-only exports: those used strict normal zero echoes.
    #[serde(default = "zero_normal_echoes")]
    pub normal_echoes: Vec<LayerEcho>,
    pub hypershift: SecondaryBindings,
}

fn zero_normal_echoes() -> Vec<LayerEcho> {
    (1..=16)
        .map(|button| LayerEcho { button, layer: 0 })
        .collect()
}

impl LayerReadback {
    pub(super) fn normal_echo(&self, button: u8) -> u8 {
        self.normal_echoes
            .iter()
            .find(|e| e.button == button)
            .map_or(0, |e| e.layer)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SecondaryBindings {
    pub layer: u8,
    /// Primary clicks are not part of the secondary writer's permitted scope.
    pub primary_inspected: bool,
    /// V2 Pro firmware can return layer zero while the requested selector
    /// changes the records. Preserve that observed metadata explicitly.
    pub echoes: Vec<LayerEcho>,
    pub buttons: Vec<Button>,
    pub controls: Vec<Button>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerEcho {
    pub button: u8,
    pub layer: u8,
}

/// Forensic reply evidence only. This must never be treated as a verified bank
/// or accepted by any restoration/preparation writer.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerReplyProbe {
    pub format: u8,
    pub kind: String,
    pub secondary_verified: bool,
    pub normal: Snapshot,
    pub replies: Vec<LayerReply>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerReply {
    pub button: u8,
    pub wire_id: u8,
    pub requested_layer: u8,
    pub echoed_layer: u8,
    pub record: [u8; 7],
    pub matches_normal_wire: bool,
}

impl<T: Transport> Mouse<T> {
    /// Recovery evidence only: retain both requested and returned selectors.
    /// Unlike read_layers, no bank identity is inferred from the returned byte.
    /// This cannot deserialize as a Snapshot, LayerReadback or paired backup.
    pub fn inspect_mapping_selectors(&mut self) -> Result<serde_json::Value> {
        ensure!(
            matches!(self.transport.identity().product, 0xa7 | 0xa8),
            "Selector inspection requires Naga V2 Pro"
        );
        let metadata = |mouse: &mut Self| -> Result<serde_json::Value> {
            ensure!(
                crate::faceplate::read(mouse)?.buttons == Some(12),
                "Selector inspection requires the twelve-button plate"
            );
            let serial = mouse.transport.exchange(0, 0x82, &[0; 22], 0)?;
            ensure!(
                serial.len() == 22 && serial.iter().any(|b| *b != 0),
                "Invalid mouse serial"
            );
            Ok(
                serde_json::json!({"device":mouse.transport.identity(), "serial_bytes":serial,
                "mode":mouse.get_mode()?, "inventory":mouse.slot_inventory()?}),
            )
        };
        let before = metadata(self)?;
        let slot = before["inventory"]["active"]
            .as_u64()
            .context("Missing active slot")? as u8;
        slot_valid(slot)?;
        ensure!(
            before["inventory"]["initialized"]
                .as_array()
                .context("Invalid inventory")?
                .iter()
                .any(|id| id.as_u64() == Some(u64::from(slot))),
            "Active slot is not initialized"
        );
        let capture = |mouse: &mut Self| -> Result<Vec<serde_json::Value>> {
            let mut records = Vec::new();
            // Complete each selector sweep before changing selector. Adjacent
            // requests use different wire IDs, retaining stale-address checks.
            for selector in [0, 1] {
                let ids = if selector == 0 { vec![1, 2, 3] } else { vec![] };
                for (logical, wire) in ids.into_iter().map(|id| (None, id)).chain(
                    (1..=16)
                        .map(|id| control_id(id).map(|wire| (Some(id), wire)))
                        .collect::<Result<Vec<_>>>()?,
                ) {
                    let mut request = [0; 10];
                    request[..3].copy_from_slice(&[slot, wire, selector]);
                    let reply = mouse
                        .transport
                        .exchange(2, 0x8c, &request, 2)
                        .with_context(|| {
                            format!("Observing slot {slot}, wire {wire:#04x}, selector {selector}")
                        })?;
                    ensure!(
                        reply.len() == 10 && reply[..2] == request[..2] && reply[2] <= 1,
                        "Invalid selector observation reply"
                    );
                    records.push(serde_json::json!({"logical":logical, "wire":wire,
                        "requested_layer":selector, "echoed_layer":reply[2], "record":reply[3..]}));
                }
            }
            Ok(records)
        };
        let records = capture(self)?;
        ensure!(
            records == capture(self)?,
            "Selector replies changed between sweeps"
        );
        ensure!(
            before == metadata(self)?,
            "Mouse metadata or faceplate changed during inspection"
        );
        Ok(
            serde_json::json!({"format":1,"kind":"unverified_selector_observations",
            "bank_identity_verified":false,"metadata":before,"slot":slot,"records":records}),
        )
    }

    fn observe_layer_replies(&mut self, normal: &Snapshot) -> Result<Vec<LayerReply>> {
        let mut replies = Vec::new();
        for button in normal.buttons.iter().chain(&normal.controls) {
            let id = control_id(button.button)?;
            let mut request = [0; 10];
            request[..3].copy_from_slice(&[normal.slot, id, MappingLayer::Hypershift as u8]);
            // Diagnostic-only: transport still validates report, transaction,
            // class, command, status, checksum and slot/button echoes. Preserve
            // the layer echo explicitly, without asserting a bank identity.
            let bytes = self
                .transport
                .exchange(2, 0x8c, &request, 2)
                .with_context(|| {
                    format!(
                        "Reading slot {}, button {} (wire {id:#04x}), layer 1 (reply observation)",
                        normal.slot, button.button
                    )
                })?;
            ensure!(
                bytes.len() == 10 && bytes[..2] == request[..2],
                "Invalid diagnostic mapping reply"
            );
            let record: [u8; 7] = bytes[3..].try_into().unwrap();
            replies.push(LayerReply {
                button: button.button,
                wire_id: id,
                requested_layer: MappingLayer::Hypershift as u8,
                echoed_layer: bytes[2],
                record,
                matches_normal_wire: record == button.record()?,
            });
        }
        Ok(replies)
    }

    /// Capture mismatched-bank replies without ever exposing them as secondary
    /// bindings. The parsed reader separately applies the bounded V2 Pro quirk.
    pub fn probe_layer_replies(&mut self, slot: Option<u8>) -> Result<LayerReplyProbe> {
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Layer reply inspection requires the twelve-button plate"
        );
        let normal = self.read(slot)?;
        let replies = self.observe_layer_replies(&normal)?;
        ensure!(
            replies == self.observe_layer_replies(&normal)?,
            "Diagnostic replies changed between reads"
        );
        ensure!(
            normal == self.read(Some(normal.slot))?,
            "Normal state changed during reply inspection"
        );
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Faceplate changed during reply inspection"
        );
        Ok(LayerReplyProbe {
            format: 1,
            kind: "unverified_layer_replies".into(),
            secondary_verified: false,
            normal,
            replies,
        })
    }

    fn secondary_bindings(&mut self, normal: &Snapshot) -> Result<SecondaryBindings> {
        ensure!(
            matches!(normal.device.product, 0xa7 | 0xa8),
            "Secondary echo handling is restricted to Naga V2 Pro USB/receiver"
        );
        let replies = self.observe_layer_replies(normal)?;
        let mut buttons = Vec::new();
        let mut controls = Vec::new();
        let mut echoes = Vec::new();
        for reply in replies {
            ensure!(
                reply.echoed_layer <= 1,
                "Unexpected secondary layer echo {}",
                reply.echoed_layer
            );
            let button = Button::from_record(reply.button, reply.record)?;
            echoes.push(LayerEcho {
                button: reply.button,
                layer: reply.echoed_layer,
            });
            if reply.button <= 12 {
                buttons.push(button);
            } else {
                controls.push(button);
            }
        }
        Ok(SecondaryBindings {
            layer: MappingLayer::Hypershift as u8,
            primary_inspected: false,
            echoes,
            buttons,
            controls,
        })
    }

    /// Single-pass UI read. Transactions must still capture/check a fresh backup
    /// with read_layers before writing; this view is not a recovery checkpoint.
    pub(crate) fn preview_layers(&mut self, slot: Option<u8>) -> Result<LayerReadback> {
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Layer inspection requires the twelve-button plate"
        );
        let (normal, normal_echoes) = self.read_with_layer_echoes(slot)?;
        let hypershift = self.secondary_bindings(&normal)?;
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Faceplate changed during layer inspection"
        );
        Ok(LayerReadback {
            format: 1,
            normal,
            normal_echoes,
            hypershift,
        })
    }

    /// Compare two reads of each bank and the plate; never activate or write.
    /// This guards against observed changes, not concurrent firmware transactions.
    pub fn read_layers(&mut self, slot: Option<u8>) -> Result<LayerReadback> {
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Layer inspection requires the twelve-button plate"
        );
        let (normal, normal_echoes) = self
            .read_with_layer_echoes(slot)
            .context("First normal-bank read")?;
        let hypershift = self.secondary_bindings(&normal).with_context(|| {
            format!(
                "First Hypershift-bank read (product {:04x})",
                normal.device.product
            )
        })?;
        let second = self
            .secondary_bindings(&normal)
            .context("Second Hypershift-bank read")?;
        ensure!(
            hypershift == second,
            "Hypershift records changed during inspection; stop other controllers and read again"
        );
        ensure!(
            (normal.clone(), normal_echoes.clone())
                == self
                    .read_with_layer_echoes(Some(normal.slot))
                    .context("Final normal-bank read")?,
            "Normal bindings or device state changed during layer inspection"
        );
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Faceplate changed during layer inspection"
        );
        Ok(LayerReadback {
            format: 1,
            normal,
            normal_echoes,
            hypershift,
        })
    }
}
