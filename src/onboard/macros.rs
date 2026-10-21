//! Native Device167 macro-storage getters. No allocation, upload or deletion.
use super::*;

// Diagnostic resource bounds, not advertised firmware capacities.
const MAX_MACROS: usize = 1024;
const MAX_DATA: usize = 1024 * 1024;
const MAX_TOTAL: usize = 4 * MAX_DATA;
const METADATA_SIZE: usize = 250;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub command: u8,
    pub request: Vec<u8>,
    pub response: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Entry {
    pub id: u16,
    /// Opaque native metadata, including unknown and unused bytes.
    pub metadata: Vec<u8>,
    pub data: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Storage {
    pub max_macros: u16,
    pub stored_count: u16,
    pub storage_bytes: u32,
    pub free_bytes: u32,
    pub reclaimable_bytes: u32,
    pub entries: Vec<Entry>,
    pub records: Vec<Record>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Inspection {
    pub format: u8,
    pub kind: String,
    pub restorable: bool,
    pub guard: haptic::Guard,
    /// Scoped normal/secondary records; secondary primary mappings are unknown.
    pub mappings: Vec<layers::LayerReadback>,
    pub storage: Storage,
}

fn be16(bytes: &[u8]) -> u16 {
    u16::from_be_bytes(bytes[..2].try_into().unwrap())
}

fn be32(bytes: &[u8]) -> u32 {
    u32::from_be_bytes(bytes[..4].try_into().unwrap())
}

fn query<T: Transport>(
    mouse: &mut Mouse<T>,
    records: &mut Vec<Record>,
    command: u8,
    request: Vec<u8>,
    echo: usize,
) -> Result<Vec<u8>> {
    // Explicit getter allowlist: never reproduce CStorage's destructive cache
    // maintenance while enumerating metadata with an empty GUID.
    ensure!(
        [0x80, 0x88, 0x89, 0x8b, 0x8c, 0x8e].contains(&command),
        "Not a macro-storage getter"
    );
    let response = mouse
        .transport
        .exchange(6, command, &request, echo)
        .with_context(|| format!("Reading macro storage 06/{command:02x}"))?;
    ensure!(
        response.len() == request.len() && response[..echo] == request[..echo],
        "Invalid macro-storage 06/{command:02x} length or echo"
    );
    records.push(Record {
        command,
        request,
        response: response.clone(),
    });
    Ok(response)
}

impl<T: Transport> Mouse<T> {
    pub(super) fn macro_storage(&mut self) -> Result<Storage> {
        let mut records = Vec::new();
        let capacity = query(self, &mut records, 0x8e, vec![0; 14], 0)?;
        let max_macros = be16(&capacity);
        let storage_bytes = be32(&capacity[2..]);
        let free_bytes = be32(&capacity[6..]);
        let reclaimable_bytes = be32(&capacity[10..]);
        let count = query(self, &mut records, 0x80, vec![0; 2], 0)?;
        let stored_count = be16(&count);
        ensure!(
            stored_count <= max_macros && usize::from(stored_count) <= MAX_MACROS,
            "Macro count exceeds capacity or diagnostic resource bound"
        );
        let mut ids = Vec::new();
        while ids.len() < usize::from(stored_count) {
            let n = (usize::from(stored_count) - ids.len()).min(32);
            let mut request = vec![0; 4 + 2 * n];
            request[..2].copy_from_slice(&(ids.len() as u16).to_be_bytes());
            // Native getter leaves bytes 2..4 zero; retain the response without
            // guessing whether that field is a returned count or another tag.
            let response = query(self, &mut records, 0x8b, request, 2)?;
            ids.extend(
                response[4..]
                    .as_chunks::<2>()
                    .0
                    .iter()
                    .map(|pair| be16(pair)),
            );
        }
        ensure!(
            ids.iter().collect::<BTreeSet<_>>().len() == ids.len(),
            "Duplicate macro storage ID"
        );
        let mut total = 0usize;
        let mut entries = Vec::new();
        for id in ids {
            let mut request = vec![0; 6];
            request[..2].copy_from_slice(&id.to_be_bytes());
            let size = query(self, &mut records, 0x88, request, 2)?;
            let size = usize::try_from(be32(&size[2..])).context("Macro size overflow")?;
            ensure!(
                size <= MAX_DATA && size <= MAX_TOTAL - total,
                "Macro storage exceeds diagnostic resource bound"
            );
            total += size;
            let mut metadata = Vec::new();
            while metadata.len() < METADATA_SIZE {
                let n = (METADATA_SIZE - metadata.len()).min(64);
                let mut request = vec![0; 6 + n];
                request[..2].copy_from_slice(&id.to_be_bytes());
                request[2..4].copy_from_slice(&(metadata.len() as u16).to_be_bytes());
                // Native metadata getter leaves bytes 4..6 zero. The setter
                // uses a total length here; do not copy setter framing to reads.
                let response = query(self, &mut records, 0x8c, request, 4)?;
                metadata.extend_from_slice(&response[6..]);
            }
            let mut data = Vec::new();
            while data.len() < size {
                let n = (size - data.len()).min(72);
                let mut request = vec![0; 7 + n];
                request[..2].copy_from_slice(&id.to_be_bytes());
                request[2..6].copy_from_slice(&(data.len() as u32).to_be_bytes());
                request[6] = n as u8;
                let response = query(self, &mut records, 0x89, request, 7)?;
                data.extend_from_slice(&response[7..]);
            }
            entries.push(Entry { id, metadata, data });
        }
        Ok(Storage {
            max_macros,
            stored_count,
            storage_bytes,
            free_bytes,
            reclaimable_bytes,
            entries,
            records,
        })
    }

    /// Wired/twelve-button diagnostic only, deliberately not a restore format.
    pub fn inspect_macros(&mut self) -> Result<Inspection> {
        // Reuse the existing identity/normal-mode/plate/inventory guard without
        // sending any wheel requests. Receiver live validation is separate.
        let guard = self.haptic_guard().context("Macro inspection scope")?;
        let mut mappings = Vec::new();
        for &slot in &guard.slots {
            let mapping = self.read_layers(Some(slot))?;
            let normal = &mapping.normal;
            ensure!(
                normal.device == guard.device
                    && normal.mode == guard.mode
                    && normal.slots == guard.slots
                    && normal.slot_capacity == Some(guard.capacity)
                    && normal.active == guard.active,
                "Mapping state differs from macro inspection guard"
            );
            mappings.push(mapping);
        }
        let storage = self.macro_storage()?;
        ensure!(
            self.haptic_guard()? == guard,
            "Mouse state changed during macro inspection"
        );
        ensure!(
            self.macro_storage()? == storage,
            "Macro storage changed between reads"
        );
        for mapping in &mappings {
            ensure!(
                self.read_layers(Some(mapping.normal.slot))? == *mapping,
                "Mapping references changed during macro inspection"
            );
        }
        ensure!(
            self.haptic_guard()? == guard,
            "Mouse state changed during macro inspection"
        );
        Ok(Inspection {
            format: 1,
            kind: "onboard_macro_diagnostic".into(),
            restorable: false,
            guard,
            mappings,
            storage,
        })
    }
}

/// Validate an untrusted export by replaying only its retained getter records.
/// No hardware is opened and no data is synthesized for absent records.
pub fn validate_inspection(inspection: &Inspection) -> Result<()> {
    ensure!(
        inspection.format == 1
            && inspection.kind == "onboard_macro_diagnostic"
            && !inspection.restorable,
        "Not a macro diagnostic export"
    );
    let guard = &inspection.guard;
    ensure!(
        guard.device.product == 0xa7
            && !guard.device.serial.is_empty()
            && guard.mode == [0, 0]
            && guard.module_id == 3
            && (1..=5).contains(&guard.capacity)
            && !guard.slots.is_empty()
            && guard.slots.len() <= usize::from(guard.capacity)
            && guard.slots.contains(&guard.active)
            && guard.slots.iter().all(|s| *s >= 1 && *s <= guard.capacity)
            && guard.slots.iter().collect::<BTreeSet<_>>().len() == guard.slots.len(),
        "Invalid macro diagnostic guard"
    );
    ensure!(
        inspection
            .mappings
            .iter()
            .map(|m| m.normal.slot)
            .collect::<Vec<_>>()
            == guard.slots,
        "Incomplete macro reference checkpoint"
    );
    for mapping in &inspection.mappings {
        layer_transaction::validate_state(mapping)?;
        let normal = &mapping.normal;
        ensure!(
            normal.device == guard.device
                && normal.mode == guard.mode
                && normal.active == guard.active
                && normal.slots == guard.slots
                && normal.slot_capacity == Some(guard.capacity),
            "Inconsistent macro reference checkpoint"
        );
        ensure!(
            normal.primary.len() == 2
                && normal.primary.iter().map(|b| b.button).collect::<Vec<_>>() == [1, 2],
            "Missing normal primary records"
        );
        for record in &normal.primary {
            record.record()?;
        }
    }
    struct Recorded<'a> {
        identity: Identity,
        records: std::slice::Iter<'a, Record>,
    }
    impl Transport for Recorded<'_> {
        fn identity(&self) -> Identity {
            self.identity.clone()
        }
        fn exchange(
            &mut self,
            class: u8,
            command: u8,
            request: &[u8],
            _: usize,
        ) -> Result<Vec<u8>> {
            let record = self.records.next().context("Missing macro getter record")?;
            ensure!(
                class == 6 && command == record.command && request == record.request,
                "Macro getter record does not match decoded storage"
            );
            Ok(record.response.clone())
        }
    }
    let mut replay = Mouse {
        transport: Recorded {
            identity: guard.device.clone(),
            records: inspection.storage.records.iter(),
        },
    };
    let storage = replay.macro_storage()?;
    ensure!(
        replay.transport.records.next().is_none() && storage == inspection.storage,
        "Macro getter records and decoded storage differ"
    );
    Ok(())
}

/// Durable content checkpoint format. It preserves all inventoried macro data,
/// but never claims complete profile/reference coverage or an available restore.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Checkpoint {
    pub format: u8,
    pub kind: String,
    pub complete_profile: bool,
    pub restoration_implemented: bool,
    pub inspection: Inspection,
}

impl Checkpoint {
    pub fn from_inspection(inspection: Inspection) -> Result<Self> {
        validate_inspection(&inspection)?;
        Ok(Self {
            format: 1,
            kind: "onboard_macro_storage_checkpoint".into(),
            complete_profile: false,
            restoration_implemented: false,
            inspection,
        })
    }

    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.format == 1
                && self.kind == "onboard_macro_storage_checkpoint"
                && !self.complete_profile
                && !self.restoration_implemented,
            "Invalid macro storage checkpoint"
        );
        validate_inspection(&self.inspection)
    }

    /// A future transaction must perform this after durable backup, immediately
    /// before any settings writes. Reconnect may change only the hidraw path.
    pub fn check_fresh(&self, fresh: &Inspection) -> Result<()> {
        self.validate()?;
        validate_inspection(fresh)?;
        let mut expected = self.inspection.clone();
        expected.guard.device.path = fresh.guard.device.path.clone();
        for mapping in &mut expected.mappings {
            mapping.normal.device.path = fresh.guard.device.path.clone();
        }
        ensure!(
            &expected == fresh,
            "Macro storage or reference checkpoint is stale"
        );
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    struct Fake {
        replies: VecDeque<(u8, Vec<u8>, usize, Vec<u8>)>,
    }

    impl Transport for Fake {
        fn identity(&self) -> Identity {
            Identity {
                path: "mock".into(),
                product: 0xa8,
                serial: String::new(),
            }
        }

        fn exchange(
            &mut self,
            class: u8,
            command: u8,
            payload: &[u8],
            echo: usize,
        ) -> Result<Vec<u8>> {
            assert_eq!(class, 6);
            let (expected_command, expected_request, expected_echo, reply) =
                self.replies.pop_front().expect("Unexpected request");
            assert_eq!(
                (command, payload, echo),
                (expected_command, expected_request.as_slice(), expected_echo)
            );
            Ok(reply)
        }
    }

    fn mouse(count: u16) -> Mouse<Fake> {
        let mut capacity = vec![0, 64];
        for n in [512u32, 65536, 256] {
            capacity.extend(n.to_be_bytes());
        }
        Mouse {
            transport: Fake {
                replies: VecDeque::from([
                    (0x8e, vec![0; 14], 0, capacity),
                    (0x80, vec![0; 2], 0, count.to_be_bytes().to_vec()),
                ]),
            },
        }
    }

    // Synthetic replies exercising the exact native request construction;
    // these are not hardware captures or evidence of firmware acceptance.
    #[test]
    fn empty_inventory_never_reads_or_deletes_entries() -> Result<()> {
        let mut m = mouse(0);
        let s = m.macro_storage()?;
        assert!(s.entries.is_empty());
        assert_eq!(
            (s.max_macros, s.free_bytes, s.reclaimable_bytes),
            (64, 65536, 256)
        );
        assert!(m.transport.replies.is_empty());
        Ok(())
    }

    #[test]
    fn captured_wired_empty_inventory_and_capacity() -> Result<()> {
        // 2026-10-20 wired capture. Only non-identifying storage replies are
        // retained; empty inventory never exercises ID/metadata/data getters.
        let mut m = mouse(0);
        m.transport.replies.front_mut().unwrap().3 =
            vec![0, 100, 0, 1, 0xf0, 0, 0, 1, 0xeb, 0, 0, 0, 4, 0];
        let s = m.macro_storage()?;
        assert_eq!(s.max_macros, 100);
        assert_eq!(s.stored_count, 0);
        assert_eq!(s.storage_bytes, 126_976);
        assert_eq!(s.free_bytes, 125_696);
        assert_eq!(s.reclaimable_bytes, 1_024);
        assert!(s.entries.is_empty());
        assert!(m.transport.replies.is_empty());
        Ok(())
    }

    #[test]
    fn preserves_empty_metadata_unknown_events_and_chunk_boundaries() -> Result<()> {
        let mut m = mouse(1);
        let q = &mut m.transport.replies;
        q.push_back((0x8b, vec![0; 6], 2, vec![0, 0, 0, 1, 0x12, 0x34]));
        q.push_back((
            0x88,
            vec![0x12, 0x34, 0, 0, 0, 0],
            2,
            vec![0x12, 0x34, 0, 0, 0, 73],
        ));
        for (offset, n) in [(0u16, 64usize), (64, 64), (128, 64), (192, 58)] {
            let mut request = vec![0; 6 + n];
            request[..2].copy_from_slice(&[0x12, 0x34]);
            request[2..4].copy_from_slice(&offset.to_be_bytes());
            q.push_back((0x8c, request.clone(), 4, request));
        }
        for (offset, n) in [(0u32, 72usize), (72, 1)] {
            let mut request = vec![0; 7 + n];
            request[..2].copy_from_slice(&[0x12, 0x34]);
            request[2..6].copy_from_slice(&offset.to_be_bytes());
            request[6] = n as u8;
            let mut response = request.clone();
            response[7..].fill(0xfe);
            q.push_back((0x89, request, 7, response));
        }
        let s = m.macro_storage()?;
        assert_eq!(s.entries[0].metadata, vec![0; 250]);
        assert_eq!(s.entries[0].data, vec![0xfe; 73]);
        assert!(m.transport.replies.is_empty());
        let mut scope = Mouse {
            transport: Stable {
                storage_reads: 0,
                change_storage: false,
                change_mapping: false,
                change_plate: false,
                calls: vec![],
            },
        }
        .inspect_macros()?;
        scope.storage = s;
        let checkpoint = Checkpoint::from_inspection(scope.clone())?;
        checkpoint.check_fresh(&scope)?;
        // Unknown sequence contents are valid backup data. A change to the
        // parsed copy alone must fail even when the saved wire reply is intact.
        scope.storage.entries[0].data[0] = 1;
        assert!(validate_inspection(&scope).is_err());
        assert!(checkpoint.check_fresh(&scope).is_err());
        Ok(())
    }

    #[test]
    fn rejects_duplicate_ids_capacity_overflow_and_truncated_replies() {
        let mut m = mouse(65);
        assert!(
            m.macro_storage()
                .unwrap_err()
                .to_string()
                .contains("capacity")
        );
        let mut m = mouse(2);
        m.transport
            .replies
            .push_back((0x8b, vec![0; 8], 2, vec![0, 0, 0, 2, 0, 7, 0, 7]));
        assert!(
            m.macro_storage()
                .unwrap_err()
                .to_string()
                .contains("Duplicate")
        );
        let mut m = mouse(0);
        m.transport.replies.front_mut().unwrap().3.pop();
        assert!(
            m.macro_storage()
                .unwrap_err()
                .to_string()
                .contains("length or echo")
        );
    }

    #[test]
    fn rejects_wrong_echo_and_excessive_allocation_before_reading_contents() {
        let mut m = mouse(1);
        m.transport
            .replies
            .push_back((0x8b, vec![0; 6], 2, vec![1, 0, 0, 1, 0, 7]));
        assert!(m.macro_storage().is_err());
        let mut m = mouse(1);
        m.transport
            .replies
            .push_back((0x8b, vec![0; 6], 2, vec![0, 0, 0, 1, 0, 7]));
        m.transport.replies.push_back((
            0x88,
            vec![0, 7, 0, 0, 0, 0],
            2,
            vec![0, 7, 0xff, 0xff, 0xff, 0xff],
        ));
        assert!(
            m.macro_storage()
                .unwrap_err()
                .to_string()
                .contains("resource bound")
        );
    }

    #[test]
    fn receiver_is_rejected_before_requests() {
        let mut m = mouse(0);
        assert!(m.inspect_macros().is_err());
        assert_eq!(m.transport.replies.len(), 2);
    }

    struct Stable {
        storage_reads: usize,
        change_storage: bool,
        change_mapping: bool,
        change_plate: bool,
        calls: Vec<(u8, u8)>,
    }

    impl Transport for Stable {
        fn identity(&self) -> Identity {
            Identity {
                path: "mock".into(),
                product: 0xa7,
                serial: String::new(),
            }
        }
        fn exchange(
            &mut self,
            class: u8,
            command: u8,
            request: &[u8],
            _: usize,
        ) -> Result<Vec<u8>> {
            self.calls.push((class, command));
            ensure!(command >= 0x80, "Unexpected setter");
            Ok(match (class, command) {
                (0, 0x82) => {
                    let mut s = vec![0; 22];
                    s[0] = b'X';
                    s
                }
                (0, 0x84) => vec![0, 0],
                (0, 0xb9) => vec![if self.change_plate && self.storage_reads > 0 {
                    4
                } else {
                    3
                }],
                (5, 0x81) => vec![5, 1, 2],
                (5, 0x84) => vec![1, 0, 0, 0, 0, 0],
                (2, 0x8c) => {
                    let mut r = request.to_vec();
                    r[3..].copy_from_slice(&[2, 2, 0, 0x1e, 0, 0, 0]);
                    if self.change_mapping && self.storage_reads > 1 && request[1] == 0x40 {
                        r[6] = 5;
                    }
                    r
                }
                (6, 0x8e) => {
                    self.storage_reads += 1;
                    let mut r = vec![0; 14];
                    r[1] = 64;
                    if self.change_storage && self.storage_reads > 1 {
                        r[13] = 1;
                    }
                    r
                }
                (6, 0x80) => vec![0, 0],
                _ => bail!("Unexpected getter {class:02x}/{command:02x}"),
            })
        }
    }

    #[test]
    fn complete_inspection_checks_all_slots_and_rejects_changes() -> Result<()> {
        for change in 0..4 {
            let mut m = Mouse {
                transport: Stable {
                    storage_reads: 0,
                    change_storage: change == 1,
                    change_mapping: change == 2,
                    change_plate: change == 3,
                    calls: vec![],
                },
            };
            let result = m.inspect_macros();
            if change == 0 {
                let result = result?;
                assert_eq!(
                    result
                        .mappings
                        .iter()
                        .map(|m| m.normal.slot)
                        .collect::<Vec<_>>(),
                    vec![1, 2]
                );
                assert!(!result.restorable);
                assert_eq!(m.transport.storage_reads, 2);
            } else {
                assert!(result.is_err());
            }
            assert!(
                m.transport
                    .calls
                    .iter()
                    .all(|(class, cmd)| *class != 6 || [0x80, 0x8e].contains(cmd))
            );
        }
        Ok(())
    }

    #[test]
    fn inventory_pages_use_offsets_in_entries() -> Result<()> {
        let mut m = mouse(33);
        for (offset, n) in [(0u16, 32usize), (32, 1)] {
            let mut request = vec![0; 4 + 2 * n];
            request[..2].copy_from_slice(&offset.to_be_bytes());
            let mut response = request.clone();
            for (i, pair) in response[4..].as_chunks_mut::<2>().0.iter_mut().enumerate() {
                pair.copy_from_slice(&(offset + i as u16 + 1).to_be_bytes());
            }
            m.transport.replies.push_back((0x8b, request, 2, response));
        }
        // Stop after enumeration: oversize first entry proves both ID pages
        // were consumed before any contents were requested.
        m.transport.replies.push_back((
            0x88,
            vec![0, 1, 0, 0, 0, 0],
            2,
            vec![0, 1, 0xff, 0xff, 0xff, 0xff],
        ));
        assert!(
            m.macro_storage()
                .unwrap_err()
                .to_string()
                .contains("resource bound")
        );
        assert!(m.transport.replies.is_empty());
        Ok(())
    }

    #[test]
    fn checkpoint_replays_wire_evidence_and_rejects_stale_state() -> Result<()> {
        let mut m = Mouse {
            transport: Stable {
                storage_reads: 0,
                change_storage: false,
                change_mapping: false,
                change_plate: false,
                calls: vec![],
            },
        };
        let export = m.inspect_macros()?;
        let checkpoint = Checkpoint::from_inspection(export.clone())?;
        checkpoint.check_fresh(&export)?;
        let mut reconnect = export.clone();
        reconnect.guard.device.path = "reconnected".into();
        for mapping in &mut reconnect.mappings {
            mapping.normal.device.path = "reconnected".into();
        }
        checkpoint.check_fresh(&reconnect)?;
        for mode in 0..6 {
            let mut changed = export.clone();
            match mode {
                0 => changed.storage.free_bytes += 1,
                1 => {
                    changed.storage.records[0].response[13] = 1;
                    changed.storage.reclaimable_bytes = 1;
                }
                2 => changed.mappings[0].normal.buttons[0].data[1] = 5,
                3 => {
                    changed.guard.device.serial = "other".into();
                    for m in &mut changed.mappings {
                        m.normal.device.serial = "other".into();
                    }
                }
                4 => {
                    changed
                        .storage
                        .records
                        .push(changed.storage.records[0].clone());
                }
                _ => {
                    changed.mappings.pop();
                }
            }
            assert!(
                checkpoint.check_fresh(&changed).is_err(),
                "accepted mutation {mode}"
            );
        }
        let mut altered = checkpoint.clone();
        altered.complete_profile = true;
        assert!(altered.validate().is_err());
        let serialized = serde_json::to_vec(&checkpoint)?;
        let roundtrip: Checkpoint = serde_json::from_slice(&serialized)?;
        assert_eq!(roundtrip, checkpoint);
        roundtrip.validate()?;
        Ok(())
    }
}
