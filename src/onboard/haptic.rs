//! Model-specific HyperScroll getters. Never sends haptic setters.
use super::*;

const CLASS: u8 = 0x15;
// Resource bounds, not claimed firmware limits. Stop rather than allocate from
// unchecked device counts. Native chunks carry at most eight float pairs.
const MAX_POINTS: u16 = 4096;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Guard {
    pub device: Identity,
    pub mode: Vec<u8>,
    pub capacity: u8,
    pub slots: Vec<u8>,
    pub active: u8,
    pub module_id: u8,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub command: u8,
    pub request: Vec<u8>,
    pub response: Vec<u8>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rejection: Option<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub slot: u8,
    pub active_position: u8,
    pub stages: Vec<u8>,
    pub browsing_mode: u8,
    pub capacities: [u16; 3],
    pub configuration: Vec<u8>,
    pub tables: Vec<Vec<[u8; 8]>>,
    pub metadata: Vec<u8>,
    pub records: Vec<Record>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Inspection {
    pub format: u8,
    pub kind: String,
    pub guard: Guard,
    pub state: State,
}

fn be(bytes: &[u8]) -> u16 {
    u16::from_be_bytes([bytes[0], bytes[1]])
}

pub(super) fn finite(bytes: &[u8]) -> Result<()> {
    ensure!(bytes.len().is_multiple_of(4), "Truncated wheel float");
    for value in bytes.as_chunks::<4>().0 {
        ensure!(
            f32::from_le_bytes(*value).is_finite(),
            "Non-finite wheel value"
        );
    }
    Ok(())
}

pub(super) fn query<T: Transport>(
    mouse: &mut Mouse<T>,
    records: &mut Vec<Record>,
    command: u8,
    request: Vec<u8>,
    echo: usize,
) -> Result<Vec<u8>> {
    let response = mouse
        .transport
        .exchange(CLASS, command, &request, echo)
        .with_context(|| format!("Reading HyperScroll 15/{command:02x}"))?;
    ensure!(
        response.len() <= 80 && response.len() >= echo && response[..echo] == request[..echo],
        "Invalid HyperScroll 15/{command:02x} echo"
    );
    records.push(Record {
        command,
        request,
        response: response.clone(),
        rejection: None,
    });
    Ok(response)
}

impl<T: Transport> Mouse<T> {
    /// Getter-only identity-bound diagnostic. Firmware 2.61.01's USB handler
    /// 44fb6 copies exactly two version bytes for 00/81; patch is unavailable.
    pub fn inspect_haptic_firmware(&mut self) -> Result<serde_json::Value> {
        let guard = self.haptic_guard()?;
        let first = self.transport.exchange(0, 0x81, &[0, 0], 0)?;
        ensure!(first.len() == 2, "Invalid firmware version reply length");
        let second = self.transport.exchange(0, 0x81, &[0, 0], 0)?;
        ensure!(first == second, "Firmware version changed between reads");
        ensure!(
            self.haptic_guard()? == guard,
            "Mouse state changed during firmware inspection"
        );
        Ok(
            serde_json::json!({"format":1,"kind":"haptic_firmware_diagnostic",
            "guard":guard,"version_bytes":first,
            "reported_version":format!("{}.{}",first[0],first[1]),
            "patch_available":false,"stable":true}),
        )
    }

    pub(super) fn haptic_guard(&mut self) -> Result<Guard> {
        let mut device = self.transport.identity();
        ensure!(
            device.product == 0xa7,
            "HyperScroll inspection currently requires wired Naga V2 Pro (00a7)"
        );
        let serial = self.transport.exchange(0, 0x82, &[0; 22], 0)?;
        ensure!(serial.len() == 22, "Invalid serial reply");
        device.serial = String::from_utf8(serial)?
            .trim_matches(char::from(0))
            .trim()
            .to_owned();
        ensure!(!device.serial.is_empty(), "Missing mouse identity");
        let mode = self.get_mode()?;
        ensure!(
            mode == [0, 0],
            "HyperScroll inspection requires normal device mode"
        );
        let inventory = self.slot_inventory()?;
        ensure!(
            inventory.initialized.contains(&inventory.active),
            "Active slot is not initialized"
        );
        let plate = crate::faceplate::read(self)?;
        ensure!(
            plate.buttons == Some(12),
            "Initial HyperScroll inspection requires the twelve-button plate"
        );
        Ok(Guard {
            device,
            mode,
            capacity: inventory.capacity,
            slots: inventory.initialized,
            active: inventory.active,
            module_id: plate.module_id,
        })
    }

    fn haptic_state(&mut self, slot: u8, active_slot: u8) -> Result<State> {
        let mut records = Vec::new();
        let active = query(self, &mut records, 0x80, vec![slot, 0], 1)?;
        ensure!(
            active.len() == 2,
            "Invalid wheel active-stage reply: {active:02x?}"
        );
        let mut request = vec![0; 13];
        request[0] = slot;
        let stages = query(self, &mut records, 0x87, request, 1)?;
        ensure!(
            stages.len() >= 3 && stages.len() <= 13,
            "Invalid wheel stage-list reply: {stages:02x?}"
        );
        let count = usize::from(stages[2]);
        ensure!(
            (1..=10).contains(&count)
                && stages.len() >= 3 + count
                && stages[1] == active[1]
                && active[1] >= 1
                && usize::from(active[1]) <= count,
            "Invalid wheel stage count/active position: {stages:02x?}"
        );
        let enabled = stages[3..3 + count].to_vec();
        ensure!(
            enabled.iter().collect::<BTreeSet<_>>().len() == count,
            "Duplicate enabled wheel stage"
        );
        let browsing = query(self, &mut records, 0x88, vec![0], 0)?;
        ensure!(
            browsing.len() == 1,
            "Invalid wheel browsing reply: {browsing:02x?}"
        );
        let capacities = query(self, &mut records, 0x85, vec![0; 6], 0)?;
        ensure!(
            capacities.len() == 6,
            "Invalid wheel capacity reply: {capacities:02x?}"
        );
        let capacities = [
            be(&capacities[0..2]),
            be(&capacities[2..4]),
            be(&capacities[4..6]),
        ];
        ensure!(
            capacities.iter().all(|n| *n <= MAX_POINTS),
            "Wheel capacity exceeds diagnostic resource bound"
        );
        let mut request = vec![0; 26];
        request[..2].copy_from_slice(&[slot, 6]);
        let configuration = query(self, &mut records, 0x83, request, 2)?;
        ensure!(
            configuration.len() == 26,
            "Invalid wheel custom configuration: {configuration:02x?}"
        );
        finite(&configuration[4..20])?;
        let counts = [
            be(&configuration[20..22]),
            be(&configuration[22..24]),
            be(&configuration[24..26]),
        ];
        ensure!(
            counts.iter().zip(capacities).all(|(n, cap)| *n <= cap),
            "Wheel table count exceeds capacity"
        );
        let mut tables = Vec::new();
        for (table, count) in counts.into_iter().enumerate() {
            let mut points = Vec::new();
            let mut offset = 0u16;
            while offset < count {
                let n = (count - offset).min(8);
                let mut request = vec![0; 71];
                request[..3].copy_from_slice(&[slot, 6, table as u8 + 1]);
                request[3..5].copy_from_slice(&offset.to_be_bytes());
                request[5..7].copy_from_slice(&n.to_be_bytes());
                let reply = query(self, &mut records, 0x84, request, 7)?;
                ensure!(
                    reply.len() >= 7 + usize::from(n) * 8 && reply.len() <= 71,
                    "Truncated wheel table chunk"
                );
                let data = &reply[7..7 + usize::from(n) * 8];
                finite(data)?;
                points.extend(data.as_chunks::<8>().0.iter().copied());
                offset += n;
            }
            tables.push(points);
        }
        let mut request = vec![0; 66];
        request[0] = slot;
        let metadata = match query(self, &mut records, 0x89, request.clone(), 1) {
            Ok(metadata) => {
                ensure!(
                    metadata.len() >= 2
                        && metadata.len() <= 66
                        && metadata[1] <= 64
                        && metadata.len() >= 2 + usize::from(metadata[1]),
                    "Invalid wheel metadata reply: {metadata:02x?}"
                );
                metadata[2..2 + usize::from(metadata[1])].to_vec()
            }
            Err(error)
                if slot != active_slot
                    && error.downcast_ref::<hidraw::Rejected>().is_some_and(|r| {
                        r.class == CLASS && r.command == 0x89 && r.status == 3
                    }) =>
            {
                // An inactive slot rejected metadata during the first live
                // preparation. Retain negative evidence; never call it empty
                // or restore it, and never swallow active-slot/transport errors.
                records.push(Record {
                    command: 0x89,
                    request,
                    response: vec![],
                    rejection: Some(3),
                });
                vec![]
            }
            Err(error) => {
                return Err(error).with_context(|| format!("Reading slot {slot} wheel metadata"));
            }
        };
        Ok(State {
            slot,
            active_position: active[1],
            stages: enabled,
            browsing_mode: browsing[0],
            capacities,
            configuration,
            tables,
            metadata,
            records,
        })
    }

    /// Double-read all wheel fields with device guards around each sweep.
    /// This kind is deliberately incompatible with every restoration format.
    pub fn inspect_haptic(&mut self, slot: Option<u8>) -> Result<Inspection> {
        self.haptic_inspection(slot, true)
    }

    /// Single-pass display read; prepare_haptic still requires a complete fresh
    /// double-read match before preparing any write.
    pub(crate) fn preview_haptic(&mut self, slot: Option<u8>) -> Result<Inspection> {
        self.haptic_inspection(slot, false)
    }

    fn haptic_inspection(&mut self, slot: Option<u8>, verify: bool) -> Result<Inspection> {
        let guard = self.haptic_guard()?;
        let slot = slot.unwrap_or(guard.active);
        ensure!(guard.slots.contains(&slot), "Wheel slot is not initialized");
        let state = self.haptic_state(slot, guard.active)?;
        ensure!(
            self.haptic_guard()? == guard,
            "Mouse changed during wheel inspection"
        );
        if verify {
            let second = self.haptic_state(slot, guard.active)?;
            ensure!(
                second == state && self.haptic_guard()? == guard,
                "Wheel state changed during inspection; release scroll-mode button and close other controllers"
            );
        }
        Ok(Inspection {
            format: 1,
            kind: "haptic_diagnostic".into(),
            guard,
            state,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Mock {
        bad: Option<u8>,
        replacement: Option<(u8, Vec<u8>)>,
        reject_metadata: Option<(u8, u8)>,
        changes: bool,
        sweeps: usize,
        calls: Vec<(u8, u8)>,
        versions: Vec<Vec<u8>>,
    }
    impl Transport for Mock {
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
            _echo: usize,
        ) -> Result<Vec<u8>> {
            self.calls.push((class, command));
            ensure!(command >= 0x80, "Unexpected setter");
            if class == CLASS
                && command == 0x89
                && let Some((slot, status)) = self.reject_metadata
                && request[0] == slot
            {
                return Err(hidraw::Rejected {
                    class,
                    command,
                    status,
                }
                .into());
            }
            let mut response = match (class, command) {
                (0, 0x81) => {
                    assert_eq!(request, &[0, 0]);
                    self.versions.remove(0)
                }
                (0, 0x82) => {
                    let mut v = vec![0; 22];
                    v[0] = b'X';
                    v
                }
                (0, 0x84) => vec![0, 0],
                (5, 0x81) => vec![5, 1, 2],
                (5, 0x84) => vec![1, 0, 0, 0, 0, 0],
                (0, 0xb9) => vec![3],
                (0x15, 0x80) => {
                    self.sweeps += 1;
                    vec![request[0], 1]
                }
                (0x15, 0x87) => {
                    let mut v = vec![request[0], 1, 2, 0x81, 0xfe];
                    v.resize(13, 0xa5);
                    v
                }
                (0x15, 0x88) => vec![u8::from(self.changes && self.sweeps > 1)],
                (0x15, 0x85) => vec![0, 80, 0, 80, 0, 80],
                (0x15, 0x83) => {
                    let mut v = request.to_vec();
                    v[2] = 1;
                    v[3] = 1;
                    v[21] = 9;
                    v[23] = 1;
                    v[25] = 0;
                    v
                }
                (0x15, 0x84) => {
                    let mut v = request.to_vec();
                    let n = usize::from(be(&request[5..7]));
                    for i in 0..n {
                        v[7 + i * 8..11 + i * 8].copy_from_slice(&(i as f32).to_le_bytes());
                    }
                    v
                }
                (0x15, 0x89) => vec![request[0], 3, 0xff, 99, 0xa5],
                _ => bail!("Unexpected query {class:02x}/{command:02x}"),
            };
            if class == CLASS && self.bad == Some(command) {
                response.clear();
            }
            if class == CLASS
                && let Some((target, bytes)) = &self.replacement
                && command == *target
            {
                response = bytes.clone();
            }
            Ok(response)
        }
    }
    fn mouse() -> Mouse<Mock> {
        Mouse {
            transport: Mock {
                bad: None,
                replacement: None,
                reject_metadata: None,
                changes: false,
                sweeps: 0,
                calls: Vec::new(),
                versions: vec![vec![2, 61], vec![2, 61]],
            },
        }
    }
    #[test]
    fn display_reads_use_one_sweep_and_preserve_captured_values_and_bounds() {
        let mut preview = mouse();
        let mut strict = mouse();
        assert_eq!(
            preview.preview_haptic(None).unwrap(),
            strict.inspect_haptic(None).unwrap()
        );
        assert_eq!(preview.transport.sweeps, 1);
        assert_eq!(strict.transport.sweeps, 2);
        assert!(preview.transport.calls.iter().all(|(_, c)| *c >= 0x80));
        eprintln!(
            "Wheel display getters: {} -> {}",
            strict.transport.calls.len(),
            preview.transport.calls.len()
        );
        let mut malformed = mouse();
        malformed.transport.replacement = Some((0x87, vec![1, 1, 11]));
        assert!(malformed.preview_haptic(None).is_err());
    }

    #[test]
    fn firmware_version_is_repeated_guarded_and_getter_only_without_patch_inference() {
        let mut m = mouse();
        let report = m.inspect_haptic_firmware().unwrap();
        assert_eq!(report["reported_version"], "2.61");
        assert_eq!(report["patch_available"], false);
        assert_eq!(
            m.transport
                .calls
                .iter()
                .filter(|c| **c == (0, 0x81))
                .count(),
            2
        );
        assert!(m.transport.calls.iter().all(|(_, c)| *c >= 0x80));
    }
    #[test]
    fn malformed_or_changing_firmware_versions_are_not_exported() {
        for versions in [vec![vec![1], vec![1]], vec![vec![1, 3], vec![2, 61]]] {
            let mut m = mouse();
            m.transport.versions = versions;
            assert!(m.inspect_haptic_firmware().is_err());
        }
    }
    #[test]
    fn getter_snapshot_preserves_unknown_ids_metadata_tails_and_point_bits() {
        let mut mouse = mouse();
        let result = mouse.inspect_haptic(None).unwrap();
        assert_eq!(result.state.stages, vec![0x81, 0xfe]);
        assert_eq!(result.state.metadata, vec![255, 99, 165]);
        assert_eq!(
            result.state.tables.iter().map(Vec::len).collect::<Vec<_>>(),
            vec![9, 1, 0]
        );
        let chunks: Vec<_> = result
            .state
            .records
            .iter()
            .filter(|r| r.command == 0x84)
            .collect();
        assert_eq!(chunks.len(), 3);
        assert_eq!(&chunks[1].request[3..7], &[0, 8, 0, 1]);
        assert_eq!(
            serde_json::from_str::<Inspection>(&serde_json::to_string(&result).unwrap()).unwrap(),
            result
        );
        assert!(mouse.transport.calls.iter().all(|(_, c)| *c >= 0x80));
    }
    #[test]
    fn truncated_replies_fail_closed() {
        for command in [0x80, 0x87, 0x88, 0x85, 0x83, 0x84, 0x89] {
            let mut m = mouse();
            m.transport.bad = Some(command);
            assert!(m.inspect_haptic(None).is_err(), "{command:02x}");
        }
    }
    #[test]
    fn malformed_counts_echoes_and_resource_sizes_stop_before_table_queries() {
        for (command, reply) in [
            (0x80, vec![2, 1]),
            (0x87, vec![1, 1, 11]),
            (0x87, vec![1, 1, 2, 0x81]),
            (0x87, vec![1, 1, 2, 0x81, 0x81]),
            (0x87, vec![1, 0, 1, 0x81]),
            (0x85, vec![255; 6]),
            (0x83, {
                let mut v = vec![0; 26];
                v[..2].copy_from_slice(&[1, 6]);
                v[21] = 81;
                v
            }),
        ] {
            let mut m = mouse();
            m.transport.replacement = Some((command, reply));
            assert!(m.inspect_haptic(None).is_err(), "{command:02x}");
            assert!(!m.transport.calls.contains(&(CLASS, 0x84)));
        }
    }
    #[test]
    fn table_and_metadata_length_and_address_validation() {
        for (command, reply) in [
            (0x84, vec![1, 6, 2, 0, 0, 0, 8]),
            (0x84, vec![1, 6, 1, 0, 0, 0, 8]),
            (0x89, vec![1, 65]),
            (0x89, vec![1, 4, 1, 2, 3]),
        ] {
            let mut m = mouse();
            m.transport.replacement = Some((command, reply));
            assert!(m.inspect_haptic(None).is_err(), "{command:02x}");
        }
    }
    #[test]
    fn inactive_metadata_rejection_is_evidence_not_an_empty_success_or_transport_fallback() {
        let mut m = mouse();
        m.transport.reject_metadata = Some((2, 3));
        let result = m.inspect_haptic(Some(2)).unwrap();
        let record = result.state.records.last().unwrap();
        assert_eq!(record.command, 0x89);
        assert_eq!(record.rejection, Some(3));
        assert!(record.response.is_empty());
        assert!(result.state.metadata.is_empty());
        for (slot, status) in [(1, 3), (2, 4), (2, 5)] {
            let mut m = mouse();
            m.transport.reject_metadata = Some((slot, status));
            assert!(m.inspect_haptic(Some(slot)).is_err());
        }
        let mut m = mouse();
        m.transport.bad = Some(0x89);
        assert!(m.inspect_haptic(Some(2)).is_err());
    }
    #[test]
    fn captured_wired_configuration_counts_and_final_partial_chunks() {
        // Non-identifying payload from the first getter-only wired capture:
        // custom selector 6, mode 1, 12-degree ticks, 45/45/3 table points.
        let configuration = vec![
            1, 6, 1, 1, 0, 0, 0, 0, 0, 0, 0x40, 0x41, 0, 0, 0, 0, 0, 0, 0x40, 0x41, 0, 45, 0, 45,
            0, 3,
        ];
        let mut m = mouse();
        m.transport.replacement = Some((0x83, configuration.clone()));
        let read = m.inspect_haptic(None).unwrap();
        assert_eq!(read.state.configuration, configuration);
        assert_eq!(
            read.state.tables.iter().map(Vec::len).collect::<Vec<_>>(),
            vec![45, 45, 3]
        );
        let chunks: Vec<_> = read
            .state
            .records
            .iter()
            .filter(|r| r.command == 0x84)
            .collect();
        assert_eq!(chunks.len(), 13);
        assert_eq!(&chunks[5].request[3..7], &[0, 40, 0, 5]);
    }
    #[test]
    fn changing_state_and_uninitialized_slots_are_rejected() {
        let mut m = mouse();
        m.transport.changes = true;
        assert!(m.inspect_haptic(None).is_err());
        let mut m = mouse();
        assert!(m.inspect_haptic(Some(3)).is_err());
        assert!(!m.transport.calls.iter().any(|(c, _)| *c == CLASS));
    }
    #[test]
    fn float_validation_rejects_infinity_nan_and_partial_values() {
        for f in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            assert!(finite(&f.to_le_bytes()).is_err());
        }
        assert!(finite(&[0, 0, 0]).is_err());
        assert!(finite(&(-0.0f32).to_le_bytes()).is_ok());
    }
}
