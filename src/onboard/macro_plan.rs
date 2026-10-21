//! Offline reconstruction of native macro allocation/upload/binding. No transport.
use super::*;
use crate::config;

/// The Windows GUID memory representation used by Device167, not UUID text order.
pub fn guid_bytes(text: &str) -> Result<[u8; 16]> {
    let bytes = text.as_bytes();
    ensure!(
        bytes.len() == 36 && [8, 13, 18, 23].into_iter().all(|i| bytes[i] == b'-'),
        "Macro GUID must have the form 00112233-4455-6677-8899-aabbccddeeff"
    );
    let digits: Vec<_> = bytes
        .iter()
        .enumerate()
        .filter(|(i, _)| ![8, 13, 18, 23].contains(i))
        .map(|(_, b)| char::from(*b).to_digit(16).context("Invalid macro GUID"))
        .collect::<Result<_>>()?;
    let mut result = [0; 16];
    for (out, pair) in result.iter_mut().zip(digits.as_chunks::<2>().0) {
        *out = (pair[0] * 16 + pair[1]) as u8;
    }
    result[..4].reverse();
    result[4..6].reverse();
    result[6..8].reverse();
    ensure!(result != [0; 16], "Empty macro GUID is not permitted");
    Ok(result)
}

fn hash(guid: &[u8; 16], seed: u16) -> u16 {
    guid.iter().enumerate().fold(seed, |h, (i, b)| {
        (u16::from(*b) + 1)
            .wrapping_mul(h)
            .wrapping_add(u16::from(*b))
            .wrapping_add(i as u16)
    }) & 0x7fff
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum Playback {
    Once {},
    Counted { count: u8 },
    WhileHeld {},
    Toggle {},
    Sequence {},
}

impl Playback {
    fn binding(&self, button: u8, id: u16) -> Result<Button> {
        control_id(button)?;
        let mut data = id.to_be_bytes().to_vec();
        let category = match *self {
            Self::Once {} => {
                data.push(1);
                3
            }
            Self::Counted { count } => {
                ensure!(count != 0, "Macro repeat count must be 1..255");
                data.push(count);
                3
            }
            Self::WhileHeld {} => 4,
            Self::Toggle {} => 5,
            Self::Sequence {} => 0x0f,
        };
        Ok(Button {
            button,
            category,
            data,
            raw_record: None,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub trigger: String,
    pub guid: String,
    pub name: String,
    /// Logical grid/auxiliary position 1..16; never a primary click.
    pub button: u8,
    pub layer: u8,
    pub playback: Playback,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Reference {
    pub slot: u8,
    pub layer: u8,
    /// Primary clicks have their own address space; they can only be inspected.
    pub primary: bool,
    pub button: u8,
    pub id: u16,
}

/// Keep shared and dangling references occupied when choosing a new ID. This
/// cannot establish coverage of other plates or secondary primary clicks.
pub fn references(inspection: &macros::Inspection) -> Result<Vec<Reference>> {
    let mut result = Vec::new();
    for mapping in &inspection.mappings {
        for (layer, primary, buttons) in [
            (0, true, &mapping.normal.primary),
            (0, false, &mapping.normal.buttons),
            (0, false, &mapping.normal.controls),
            (1, false, &mapping.hypershift.buttons),
            (1, false, &mapping.hypershift.controls),
        ] {
            for b in buttons {
                b.record()?;
                let n = match b.category {
                    3 => 3,
                    4 | 5 | 0x0f => 2,
                    // Non-macro categories traced in the native binding encoder.
                    0 | 1 | 2 | 6 | 7 | 9 | 0x0a..=0x0e | 0x11 | 0x12 | 0x15 => continue,
                    _ => bail!("Unknown mapping category in macro reference scope"),
                };
                ensure!(b.data.len() == n, "Malformed macro mapping reference");
                result.push(Reference {
                    slot: mapping.normal.slot,
                    layer,
                    primary,
                    button: b.button,
                    id: u16::from_be_bytes([b.data[0], b.data[1]]),
                });
            }
        }
    }
    Ok(result)
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Packet {
    pub class: u8,
    pub command: u8,
    pub payload: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Plan {
    pub format: u8,
    pub kind: String,
    pub hardware_verified: bool,
    pub execution_enabled: bool,
    pub complete_reference_coverage: bool,
    pub checkpoint: macros::Checkpoint,
    pub request: Request,
    pub compiled: macro_codec::Compiled,
    pub entry: macros::Entry,
    pub reserved_bytes: u32,
    pub references: Vec<Reference>,
    /// Ordered allocation/metadata/data proposals. They are never submitted.
    pub upload: Vec<Packet>,
    pub original_binding: Button,
    /// Binding is a separate phase, allowed only after exact content readback.
    pub proposed_binding: Button,
}

/// New key/mouse timelines have explicit edges and no movement. Zero-fill the
/// unused name bytes, movement origin, combined-key hint and reserved tail.
/// This is a deterministic new-entry policy, not normalization of old metadata.
fn metadata(guid: [u8; 16], name: &str, event_count: u32) -> Result<Vec<u8>> {
    ensure!(
        !name.is_empty() && name.len() <= 100 && !name.contains('\0'),
        "Macro name must contain 1..100 UTF-8 bytes without NUL"
    );
    let mut result = vec![0; 250];
    result[..16].copy_from_slice(&guid);
    result[16..20].copy_from_slice(&event_count.to_le_bytes());
    result[20..20 + name.len()].copy_from_slice(name.as_bytes());
    Ok(result)
}

fn packets(entry: &macros::Entry) -> Vec<Packet> {
    let id = entry.id.to_be_bytes();
    let mut payload = id.to_vec();
    payload.extend_from_slice(&(entry.data.len() as u32).to_be_bytes());
    let mut result = vec![Packet {
        class: 6,
        command: 8,
        payload,
    }];
    for (i, bytes) in entry.metadata.chunks(64).enumerate() {
        let mut payload = id.to_vec();
        payload.extend_from_slice(&((i * 64) as u16).to_be_bytes());
        payload.extend_from_slice(&(entry.metadata.len() as u16).to_be_bytes());
        payload.extend_from_slice(bytes);
        result.push(Packet {
            class: 6,
            command: 0x0c,
            payload,
        });
    }
    for (i, bytes) in entry.data.chunks(72).enumerate() {
        let mut payload = id.to_vec();
        payload.extend_from_slice(&((i * 72) as u32).to_be_bytes());
        payload.push(bytes.len() as u8);
        payload.extend_from_slice(bytes);
        result.push(Packet {
            class: 6,
            command: 9,
            payload,
        });
    }
    result
}

/// Offline only. A checked historical export is not proof of current mouse state,
/// device acceptance, allocation ownership or a recoverable hardware transaction.
pub fn build(
    checkpoint: macros::Checkpoint,
    sequence: &config::Macro,
    request: Request,
) -> Result<Plan> {
    checkpoint.validate()?;
    ensure!(request.layer <= 1, "Macro layer must be 0 or 1");
    control_id(request.button)?;
    let compiled = macro_codec::compile(sequence)?;
    let guid = guid_bytes(&request.guid)?;
    let inspection = &checkpoint.inspection;
    let storage = &inspection.storage;
    ensure!(
        storage.stored_count < storage.max_macros,
        "Macro entry capacity is exhausted"
    );
    ensure!(
        storage.free_bytes <= storage.storage_bytes
            && storage.reclaimable_bytes <= storage.storage_bytes,
        "Invalid macro storage accounting"
    );
    ensure!(
        storage.entries.iter().all(|e| e.metadata[..16] != guid),
        "Macro GUID already exists; existing entries cannot be replaced"
    );
    let references = references(inspection)?;
    let occupied: BTreeSet<_> = storage
        .entries
        .iter()
        .map(|e| e.id)
        .chain(references.iter().map(|r| r.id))
        .collect();
    let id = (0..5)
        .map(|seed| hash(&guid, seed))
        .find(|id| !occupied.contains(id))
        .context("All five native macro ID candidates collide; choose a new GUID")?;
    let reserved_bytes = (compiled.data.len() as u32 / 256 + 2) * 256;
    ensure!(
        reserved_bytes <= storage.free_bytes,
        "Insufficient contiguous macro storage; compaction is not permitted"
    );
    let entry = macros::Entry {
        id,
        metadata: metadata(guid, &request.name, compiled.event_count)?,
        data: compiled.data.clone(),
    };
    let mapping = inspection
        .mappings
        .iter()
        .find(|m| m.normal.slot == inspection.guard.active)
        .context("Missing active-slot mapping checkpoint")?;
    let original_binding = if request.layer == 0 {
        mapping
            .normal
            .buttons
            .iter()
            .chain(&mapping.normal.controls)
    } else {
        mapping
            .hypershift
            .buttons
            .iter()
            .chain(&mapping.hypershift.controls)
    }
    .find(|b| b.button == request.button)
    .context("Missing target binding")?
    .clone();
    let proposed_binding = request.playback.binding(request.button, id)?;
    Ok(Plan {
        format: 1,
        kind: "onboard_macro_upload_plan".into(),
        hardware_verified: false,
        execution_enabled: false,
        complete_reference_coverage: false,
        upload: packets(&entry),
        checkpoint,
        request,
        compiled,
        entry,
        reserved_bytes,
        references,
        original_binding,
        proposed_binding,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use macros::{Checkpoint, Entry, Inspection, Record, Storage};

    // Synthetic contents and mappings; capacity/count payload is from the
    // non-identifying wired capture. Nonempty getter replies are not captures.
    fn checkpoint(entries: Vec<Entry>) -> Checkpoint {
        let device = Identity {
            path: "mock".into(),
            product: 0xa7,
            serial: "TEST".into(),
        };
        let keys = |start, end| {
            (start..=end)
                .map(|button| Button {
                    button,
                    category: 2,
                    data: vec![0, 4],
                    raw_record: None,
                })
                .collect::<Vec<_>>()
        };
        let normal = Snapshot {
            format: 1,
            device: device.clone(),
            slots: vec![1],
            slot_capacity: Some(5),
            active: 1,
            slot: 1,
            mode: vec![0, 0],
            primary: (1..=2)
                .map(|button| Button {
                    button,
                    category: 1,
                    data: vec![button],
                    raw_record: None,
                })
                .collect(),
            buttons: keys(1, 12),
            controls: keys(13, 16),
        };
        let echoes = || {
            (1..=16)
                .map(|button| layers::LayerEcho { button, layer: 0 })
                .collect()
        };
        let mapping = layers::LayerReadback {
            format: 1,
            normal_echoes: echoes(),
            hypershift: layers::SecondaryBindings {
                layer: 1,
                primary_inspected: false,
                echoes: echoes(),
                buttons: normal.buttons.clone(),
                controls: normal.controls.clone(),
            },
            normal,
        };
        let mut storage = Storage {
            max_macros: 100,
            stored_count: entries.len() as u16,
            storage_bytes: 126_976,
            free_bytes: 125_696,
            reclaimable_bytes: 1024,
            entries,
            records: vec![],
        };
        evidence(&mut storage);
        Checkpoint::from_inspection(Inspection {
            format: 1,
            kind: "onboard_macro_diagnostic".into(),
            restorable: false,
            guard: haptic::Guard {
                device,
                mode: vec![0, 0],
                capacity: 5,
                slots: vec![1],
                active: 1,
                module_id: 3,
            },
            mappings: vec![mapping],
            storage,
        })
        .unwrap()
    }

    fn evidence(storage: &mut Storage) {
        let mut capacity = storage.max_macros.to_be_bytes().to_vec();
        for n in [
            storage.storage_bytes,
            storage.free_bytes,
            storage.reclaimable_bytes,
        ] {
            capacity.extend(n.to_be_bytes());
        }
        let mut records = vec![
            Record {
                command: 0x8e,
                request: vec![0; 14],
                response: capacity,
            },
            Record {
                command: 0x80,
                request: vec![0; 2],
                response: storage.stored_count.to_be_bytes().to_vec(),
            },
        ];
        if !storage.entries.is_empty() {
            let request = vec![0; 4 + storage.entries.len() * 2];
            let mut response = vec![0, 0, 0, storage.entries.len() as u8];
            for e in &storage.entries {
                response.extend(e.id.to_be_bytes());
            }
            records.push(Record {
                command: 0x8b,
                request,
                response,
            });
        }
        for entry in &storage.entries {
            let mut request = entry.id.to_be_bytes().to_vec();
            request.extend([0; 4]);
            let mut response = entry.id.to_be_bytes().to_vec();
            response.extend((entry.data.len() as u32).to_be_bytes());
            records.push(Record {
                command: 0x88,
                request,
                response,
            });
            for (i, bytes) in entry.metadata.chunks(64).enumerate() {
                let mut request = entry.id.to_be_bytes().to_vec();
                request.extend(((i * 64) as u16).to_be_bytes());
                request.resize(6 + bytes.len(), 0);
                let mut response = request.clone();
                response[6..].copy_from_slice(bytes);
                records.push(Record {
                    command: 0x8c,
                    request,
                    response,
                });
            }
            for (i, bytes) in entry.data.chunks(72).enumerate() {
                let mut request = entry.id.to_be_bytes().to_vec();
                request.extend(((i * 72) as u32).to_be_bytes());
                request.push(bytes.len() as u8);
                request.resize(7 + bytes.len(), 0);
                let mut response = request.clone();
                response[7..].copy_from_slice(bytes);
                records.push(Record {
                    command: 0x89,
                    request,
                    response,
                });
            }
        }
        storage.records = records;
    }

    fn request() -> Request {
        Request {
            trigger: "KEY_1".into(),
            guid: "00000000-0000-0000-0000-000000000001".into(),
            name: "Test".into(),
            button: 1,
            layer: 0,
            playback: Playback::Once {},
        }
    }

    fn sequence() -> config::Macro {
        config::parse("tap_ms=20\n[[binding]]\ntrigger='KEY_1'\nsteps=[{tap='KEY_B'}]")
            .unwrap()
            .into_values()
            .next()
            .unwrap()
    }

    #[test]
    fn guid_layout_native_hash_and_utf8_metadata_limits() -> Result<()> {
        let guid = guid_bytes("00112233-4455-6677-8899-aabbccddeeff")?;
        assert_eq!(
            guid,
            [
                0x33, 0x22, 0x11, 0, 0x55, 0x44, 0x77, 0x66, 0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd,
                0xee, 0xff
            ]
        );
        let sparse = guid_bytes(&request().guid)?;
        assert_eq!(
            (0..5).map(|seed| hash(&sparse, seed)).collect::<Vec<_>>(),
            [226, 228, 230, 232, 234]
        );
        for bad in [
            "",
            "00000000-0000-0000-0000-000000000000",
            "00112233_4455-6677-8899-aabbccddeeff",
            "00112233-4455-6677-8899-aabbccddeeZZ",
        ] {
            assert!(guid_bytes(bad).is_err());
        }
        let name = "é".repeat(50);
        let bytes = metadata(guid, &name, 0x12345678)?;
        assert_eq!(&bytes[..16], &guid);
        assert_eq!(&bytes[16..20], &[0x78, 0x56, 0x34, 0x12]);
        assert_eq!(&bytes[20..120], name.as_bytes());
        assert_eq!(&bytes[120..], &[0; 130]);
        for bad in ["".into(), "x\0y".into(), "é".repeat(51), "x".repeat(101)] {
            assert!(metadata(guid, &bad, 1).is_err());
        }
        Ok(())
    }

    #[test]
    fn native_upload_framing_partial_chunks_and_separate_playback() -> Result<()> {
        let entry = Entry {
            id: 0x1234,
            metadata: (0..250).collect(),
            data: vec![0x55; 145],
        };
        let upload = packets(&entry);
        assert_eq!(upload.len(), 8);
        assert_eq!(upload[0].payload, [0x12, 0x34, 0, 0, 0, 145]);
        assert_eq!(
            upload.iter().map(|p| p.command).collect::<Vec<_>>(),
            [8, 12, 12, 12, 12, 9, 9, 9]
        );
        assert!(upload.iter().all(|p| p.class == 6));
        assert_eq!(&upload[1].payload[..6], &[0x12, 0x34, 0, 0, 0, 250]);
        assert_eq!(&upload[4].payload[..6], &[0x12, 0x34, 0, 192, 0, 250]);
        assert_eq!(upload[4].payload.len(), 64); // six header bytes plus 58 data bytes
        assert_eq!(&upload[6].payload[..7], &[0x12, 0x34, 0, 0, 0, 72, 72]);
        assert_eq!(upload[7].payload, [0x12, 0x34, 0, 0, 0, 144, 1, 0x55]);
        for (mode, expected) in [
            (Playback::Once {}, [3, 3, 0x12, 0x34, 1, 0, 0]),
            (
                Playback::Counted { count: 255 },
                [3, 3, 0x12, 0x34, 255, 0, 0],
            ),
            (Playback::WhileHeld {}, [4, 2, 0x12, 0x34, 0, 0, 0]),
            (Playback::Toggle {}, [5, 2, 0x12, 0x34, 0, 0, 0]),
            (Playback::Sequence {}, [15, 2, 0x12, 0x34, 0, 0, 0]),
        ] {
            assert_eq!(mode.binding(16, 0x1234)?.record()?, expected);
        }
        assert!(Playback::Counted { count: 0 }.binding(1, 1).is_err());
        assert!(serde_json::from_str::<Playback>(r#"{"mode":"counted","count":256}"#).is_err());
        assert!(serde_json::from_str::<Playback>(r#"{"mode":"once","count":2}"#).is_err());
        Ok(())
    }

    #[test]
    fn plans_fresh_contents_preserving_old_checkpoint_and_wire_records() -> Result<()> {
        let original = checkpoint(vec![]);
        let plan = build(original.clone(), &sequence(), request())?;
        assert_eq!(plan.checkpoint, original);
        assert_eq!(plan.entry.id, 226);
        assert_eq!(plan.entry.data, [1, 5, 0x11, 20, 2, 5]);
        assert_eq!(&plan.entry.metadata[16..20], &[3, 0, 0, 0]);
        assert_eq!(&plan.entry.metadata[20..25], b"Test\0");
        assert_eq!(plan.reserved_bytes, 512);
        assert_eq!(plan.upload.len(), 6);
        assert!(
            !plan.hardware_verified && !plan.execution_enabled && !plan.complete_reference_coverage
        );
        assert_eq!(
            plan.original_binding,
            original.inspection.mappings[0].normal.buttons[0]
        );
        assert!(serde_json::from_value::<Snapshot>(serde_json::to_value(&plan)?).is_err());
        let old = Entry {
            id: 230,
            metadata: vec![0xab; 250],
            data: vec![0xfe, 0x99],
        };
        let mut checkpoint = checkpoint(vec![old.clone()]);
        checkpoint.inspection.mappings[0].normal.buttons[0] = Playback::Once {}.binding(1, 226)?;
        checkpoint.inspection.mappings[0].normal.controls[0] =
            Playback::Toggle {}.binding(13, 226)?;
        checkpoint.inspection.mappings[0].hypershift.controls[3] =
            Playback::WhileHeld {}.binding(16, 228)?;
        let mut spec = request();
        spec.button = 16;
        spec.layer = 1;
        let plan = build(checkpoint.clone(), &sequence(), spec)?;
        assert_eq!(plan.entry.id, 232);
        assert_eq!(plan.references.len(), 3); // shared and dangling IDs remain occupied
        assert_eq!(plan.checkpoint, checkpoint);
        assert_eq!(plan.checkpoint.inspection.storage.entries, [old]);
        assert_eq!(
            plan.original_binding,
            Playback::WhileHeld {}.binding(16, 228)?
        );
        Ok(())
    }

    #[test]
    fn references_in_other_slots_and_primary_reads_reserve_ids() -> Result<()> {
        let mut c = checkpoint(vec![]);
        c.inspection.guard.slots = vec![1, 2];
        c.inspection.mappings[0].normal.slots = vec![1, 2];
        let mut second = c.inspection.mappings[0].clone();
        second.normal.slot = 2;
        second.normal.primary[0] = Playback::Sequence {}.binding(1, 226)?;
        second.hypershift.buttons[0] = Playback::Toggle {}.binding(1, 228)?;
        c.inspection.mappings.push(second);
        let plan = build(c, &sequence(), request())?;
        assert_eq!(plan.entry.id, 230);
        assert_eq!(plan.references.len(), 2);
        assert!(plan.references.iter().all(|r| r.slot == 2));
        assert!(plan.references.iter().any(|r| r.primary && r.id == 226));
        assert!(plan.references.iter().any(|r| r.layer == 1 && r.id == 228));
        assert_eq!(plan.original_binding.category, 2); // active-slot grid, never the primary
        assert_eq!(plan.proposed_binding.button, 1);
        Ok(())
    }

    #[test]
    fn rejects_collisions_existing_guid_bad_scope_and_ambiguous_references() -> Result<()> {
        let mut c = checkpoint(vec![]);
        for (button, id) in c.inspection.mappings[0]
            .normal
            .buttons
            .iter_mut()
            .zip([226, 228, 230, 232, 234])
        {
            *button = Playback::Once {}.binding(button.button, id)?;
        }
        assert!(
            build(c, &sequence(), request())
                .unwrap_err()
                .to_string()
                .contains("collide")
        );
        let entry = Entry {
            id: 99,
            metadata: metadata(guid_bytes(&request().guid)?, "Old", 1)?,
            data: vec![0xfe],
        };
        assert!(
            build(checkpoint(vec![entry]), &sequence(), request())
                .unwrap_err()
                .to_string()
                .contains("GUID already exists")
        );
        for button in [0, 17, 0x34, 0xff] {
            let mut spec = request();
            spec.button = button;
            assert!(build(checkpoint(vec![]), &sequence(), spec).is_err());
        }
        let mut spec = request();
        spec.layer = 2;
        assert!(build(checkpoint(vec![]), &sequence(), spec).is_err());
        for category in [3, 4, 5, 15, 0xff, 0x10] {
            let mut c = checkpoint(vec![]);
            c.inspection.mappings[0].hypershift.buttons[0].category = category;
            c.inspection.mappings[0].hypershift.buttons[0].data = vec![];
            assert!(build(c, &sequence(), request()).is_err());
        }
        Ok(())
    }

    #[test]
    fn rejects_compaction_capacity_and_inconsistent_evidence() -> Result<()> {
        for (free, max, expected) in [
            (512, 100, true),
            (511, 100, false),
            (512, 0, false),
            (126_977, 100, false),
        ] {
            let mut c = checkpoint(vec![]);
            c.inspection.storage.free_bytes = free;
            c.inspection.storage.max_macros = max;
            evidence(&mut c.inspection.storage);
            assert_eq!(build(c, &sequence(), request()).is_ok(), expected);
        }
        let mut c = checkpoint(vec![]);
        c.inspection.storage.free_bytes += 1;
        assert!(build(c, &sequence(), request()).is_err());
        for (n, reserved) in [(42, 512), (43, 768)] {
            let steps = vec!["{tap='KEY_B'}"; n].join(",");
            let sequence =
                config::parse(&format!("[[binding]]\ntrigger='KEY_1'\nsteps=[{steps}]"))?
                    .into_values()
                    .next()
                    .unwrap();
            assert_eq!(
                build(checkpoint(vec![]), &sequence, request())?.reserved_bytes,
                reserved
            );
        }
        Ok(())
    }
}
