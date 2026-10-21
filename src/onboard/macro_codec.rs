//! Independently reconstructed native macro bytes. Pure conversion; no transport.
use super::*;
use crate::config;
use evdev::KeyCode;

const MAX_EVENTS: usize = 16_384;
const MAX_DURATION_MS: u64 = 300_000;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Compiled {
    pub format: u8,
    pub kind: String,
    pub hardware_verified: bool,
    pub duration_ms: u64,
    pub event_count: u32,
    pub data: Vec<u8>,
}

fn delay(data: &mut Vec<u8>, value: u32) {
    let bytes = value.to_be_bytes();
    let width = match value {
        0..=0xff => 1,
        0x100..=0xffff => 2,
        0x1_0000..=0xff_ffff => 3,
        _ => 4,
    };
    data.push(0x10 + width as u8);
    data.extend_from_slice(&bytes[4 - width..]);
}

/// Includes modifier usages e0..e7, which are independent down/up stream
/// events rather than the modifier bitmask used by single-action bindings.
fn keyboard_usage(key: KeyCode) -> Option<u8> {
    use KeyCode as K;
    let groups: &[(u8, &[KeyCode])] = &[
        (
            4,
            &[
                K::KEY_A,
                K::KEY_B,
                K::KEY_C,
                K::KEY_D,
                K::KEY_E,
                K::KEY_F,
                K::KEY_G,
                K::KEY_H,
                K::KEY_I,
                K::KEY_J,
                K::KEY_K,
                K::KEY_L,
                K::KEY_M,
                K::KEY_N,
                K::KEY_O,
                K::KEY_P,
                K::KEY_Q,
                K::KEY_R,
                K::KEY_S,
                K::KEY_T,
                K::KEY_U,
                K::KEY_V,
                K::KEY_W,
                K::KEY_X,
                K::KEY_Y,
                K::KEY_Z,
            ],
        ),
        (
            0x1e,
            &[
                K::KEY_1,
                K::KEY_2,
                K::KEY_3,
                K::KEY_4,
                K::KEY_5,
                K::KEY_6,
                K::KEY_7,
                K::KEY_8,
                K::KEY_9,
                K::KEY_0,
                K::KEY_ENTER,
                K::KEY_ESC,
                K::KEY_BACKSPACE,
                K::KEY_TAB,
                K::KEY_SPACE,
                K::KEY_MINUS,
                K::KEY_EQUAL,
                K::KEY_LEFTBRACE,
                K::KEY_RIGHTBRACE,
                K::KEY_BACKSLASH,
            ],
        ),
        (
            0x33,
            &[
                K::KEY_SEMICOLON,
                K::KEY_APOSTROPHE,
                K::KEY_GRAVE,
                K::KEY_COMMA,
                K::KEY_DOT,
                K::KEY_SLASH,
                K::KEY_CAPSLOCK,
                K::KEY_F1,
                K::KEY_F2,
                K::KEY_F3,
                K::KEY_F4,
                K::KEY_F5,
                K::KEY_F6,
                K::KEY_F7,
                K::KEY_F8,
                K::KEY_F9,
                K::KEY_F10,
                K::KEY_F11,
                K::KEY_F12,
                K::KEY_SYSRQ,
                K::KEY_SCROLLLOCK,
                K::KEY_PAUSE,
                K::KEY_INSERT,
                K::KEY_HOME,
                K::KEY_PAGEUP,
                K::KEY_DELETE,
                K::KEY_END,
                K::KEY_PAGEDOWN,
                K::KEY_RIGHT,
                K::KEY_LEFT,
                K::KEY_DOWN,
                K::KEY_UP,
                K::KEY_NUMLOCK,
                K::KEY_KPSLASH,
                K::KEY_KPASTERISK,
                K::KEY_KPMINUS,
                K::KEY_KPPLUS,
                K::KEY_KPENTER,
                K::KEY_KP1,
                K::KEY_KP2,
                K::KEY_KP3,
                K::KEY_KP4,
                K::KEY_KP5,
                K::KEY_KP6,
                K::KEY_KP7,
                K::KEY_KP8,
                K::KEY_KP9,
                K::KEY_KP0,
                K::KEY_KPDOT,
                K::KEY_102ND,
                K::KEY_COMPOSE,
            ],
        ),
        (
            0x68,
            &[
                K::KEY_F13,
                K::KEY_F14,
                K::KEY_F15,
                K::KEY_F16,
                K::KEY_F17,
                K::KEY_F18,
                K::KEY_F19,
                K::KEY_F20,
                K::KEY_F21,
                K::KEY_F22,
                K::KEY_F23,
                K::KEY_F24,
            ],
        ),
        (
            0xe0,
            &[
                K::KEY_LEFTCTRL,
                K::KEY_LEFTSHIFT,
                K::KEY_LEFTALT,
                K::KEY_LEFTMETA,
                K::KEY_RIGHTCTRL,
                K::KEY_RIGHTSHIFT,
                K::KEY_RIGHTALT,
                K::KEY_RIGHTMETA,
            ],
        ),
    ];
    if key == K::KEY_KPEQUAL {
        return Some(0x67);
    }
    groups
        .iter()
        .find_map(|(start, keys)| keys.iter().position(|k| *k == key).map(|i| start + i as u8))
}

fn mouse_bit(key: KeyCode) -> Option<u8> {
    match key {
        KeyCode::BTN_LEFT => Some(1),
        KeyCode::BTN_RIGHT => Some(2),
        KeyCode::BTN_MIDDLE => Some(4),
        KeyCode::BTN_SIDE | KeyCode::BTN_BACK => Some(8),
        KeyCode::BTN_EXTRA | KeyCode::BTN_FORWARD => Some(16),
        _ => None,
    }
}

/// Compile existing software TOML timelines without changing their scheduling.
/// Product bounds are deliberately narrower than the u32 native delay encoder.
pub fn compile(sequence: &config::Macro) -> Result<Compiled> {
    ensure!(
        sequence.remap.is_none(),
        "Held remaps are not onboard sequences; use steps"
    );
    ensure!(
        !sequence.actions.is_empty() && sequence.actions.len() <= MAX_EVENTS,
        "Empty or oversized macro sequence"
    );
    ensure!(
        sequence.duration_ms <= MAX_DURATION_MS,
        "Macro duration exceeds five minutes"
    );
    let mut data = Vec::new();
    let mut count = 0;
    let mut now = 0;
    let mut held = BTreeSet::new();
    let mut mouse = 0u8;
    for action in &sequence.actions {
        ensure!(
            action.at_ms >= now && action.at_ms <= sequence.duration_ms,
            "Macro timestamps are out of order or exceed duration"
        );
        if action.at_ms > now {
            delay(&mut data, (action.at_ms - now) as u32);
            count += 1;
        }
        now = action.at_ms;
        if let Some(bit) = mouse_bit(action.key) {
            // Canonicalize aliases by their output bit, so BTN_SIDE/BTN_BACK
            // cannot cause an early release of the same physical output.
            let id = 0x100 + u16::from(bit);
            ensure!(
                if action.pressed {
                    held.insert(id)
                } else {
                    held.remove(&id)
                },
                "Duplicate mouse press or unmatched release"
            );
            if action.pressed {
                mouse |= bit;
            } else {
                mouse &= !bit;
            }
            data.extend_from_slice(&[8, mouse]);
        } else {
            let usage = keyboard_usage(action.key).with_context(|| {
                format!(
                    "{:#?} has no supported onboard sequence encoding",
                    action.key
                )
            })?;
            ensure!(
                if action.pressed {
                    held.insert(u16::from(usage))
                } else {
                    held.remove(&u16::from(usage))
                },
                "Duplicate keyboard press or unmatched release"
            );
            data.extend_from_slice(&[if action.pressed { 1 } else { 2 }, usage]);
        }
        count += 1;
    }
    ensure!(held.is_empty() && mouse == 0, "Macro leaves outputs held");
    if now < sequence.duration_ms {
        delay(&mut data, (sequence.duration_ms - now) as u32);
        count += 1;
    }
    ensure!(
        count <= MAX_EVENTS,
        "Encoded macro exceeds event resource bound"
    );
    let decoded = decode(&data)?;
    ensure!(
        decoded.opaque_offset.is_none() && decoded.events.len() == count,
        "Encoded macro event count differs from structural readback"
    );
    Ok(Compiled {
        format: 1,
        kind: "onboard_macro_compilation".into(),
        hardware_verified: false,
        duration_ms: sequence.duration_ms,
        event_count: count as u32,
        data,
    })
}

/// Structural decoding of a diagnostic stream, retaining original bytes and
/// nonminimal delay widths. Unknown opcodes stop interpretation at that offset.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Decoded {
    pub events: Vec<DecodedEvent>,
    pub opaque_offset: Option<usize>,
    pub opaque_tail: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct DecodedEvent {
    pub offset: usize,
    pub bytes: Vec<u8>,
    pub delay_ms: Option<u32>,
}

pub fn decode(data: &[u8]) -> Result<Decoded> {
    ensure!(
        data.len() <= 1024 * 1024,
        "Macro exceeds diagnostic resource bound"
    );
    let mut events = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        ensure!(
            events.len() < MAX_EVENTS,
            "Macro exceeds event resource bound"
        );
        let length = match data[offset] {
            1 | 2 | 8 | 0x0a => 2,
            opcode @ 0x11..=0x14 => usize::from(opcode - 0x10) + 1,
            0x15 => 5,
            _ => {
                return Ok(Decoded {
                    events,
                    opaque_offset: Some(offset),
                    opaque_tail: data[offset..].to_vec(),
                });
            }
        };
        ensure!(
            data.len() - offset >= length,
            "Truncated macro event at byte {offset}"
        );
        let bytes = data[offset..offset + length].to_vec();
        let delay_ms = if (0x11..=0x14).contains(&bytes[0]) {
            Some(
                bytes[1..]
                    .iter()
                    .fold(0u32, |value, byte| (value << 8) | u32::from(*byte)),
            )
        } else {
            None
        };
        events.push(DecodedEvent {
            offset,
            bytes,
            delay_ms,
        });
        offset += length;
    }
    Ok(Decoded {
        events,
        opaque_offset: None,
        opaque_tail: vec![],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn toml(steps: &str) -> Compiled {
        let bindings = config::parse(&format!(
            "tap_ms=20\n[[binding]]\ntrigger='KEY_1'\nsteps=[{steps}]"
        ))
        .unwrap();
        compile(bindings.values().next().unwrap()).unwrap()
    }

    #[test]
    fn tap_chord_and_trailing_wait_match_native_records() {
        let result = toml("{chord=['KEY_LEFTCTRL','KEY_A']},{wait_ms=256}");
        assert_eq!(
            result.data,
            vec![1, 0xe0, 1, 4, 0x11, 20, 2, 4, 2, 0xe0, 0x12, 1, 0]
        );
        assert_eq!((result.event_count, result.duration_ms), (6, 276));
        assert!(!result.hardware_verified);
        let parsed = decode(&result.data).unwrap();
        assert_eq!(parsed.events.len(), 6);
        assert_eq!(
            parsed.events.iter().filter_map(|e| e.delay_ms).sum::<u32>(),
            276
        );
    }

    #[test]
    fn delay_boundaries_are_big_endian_and_unknown_bytes_are_preserved() {
        for (value, expected) in [
            (255, vec![0x11, 255]),
            (256, vec![0x12, 1, 0]),
            (65535, vec![0x12, 255, 255]),
            (65536, vec![0x13, 1, 0, 0]),
            (0xff_ffff, vec![0x13, 255, 255, 255]),
            (0x100_0000, vec![0x14, 1, 0, 0, 0]),
            (u32::MAX, vec![0x14, 255, 255, 255, 255]),
        ] {
            let mut bytes = vec![];
            delay(&mut bytes, value);
            assert_eq!(bytes, expected);
            assert_eq!(decode(&bytes).unwrap().events[0].delay_ms, Some(value));
        }
        let decoded = decode(&[0x12, 0, 1, 0xfe, 1, 2]).unwrap();
        assert_eq!(decoded.events[0].bytes, vec![0x12, 0, 1]);
        assert_eq!(decoded.opaque_offset, Some(3));
        assert_eq!(decoded.opaque_tail, vec![0xfe, 1, 2]);
        for bytes in [vec![1], vec![0x12, 1], vec![0x15, 0, 0, 0]] {
            assert!(decode(&bytes).is_err());
        }
    }

    #[test]
    fn overlapping_mouse_outputs_keep_state_and_canonicalize_aliases() {
        let result = toml("{down='BTN_LEFT'},{down='BTN_RIGHT'},{up='BTN_LEFT'},{up='BTN_RIGHT'}");
        assert_eq!(result.data, vec![8, 1, 8, 3, 8, 2, 8, 0]);
        let bindings=config::parse("[[binding]]\ntrigger='KEY_1'\nsteps=[{down='BTN_SIDE'},{down='BTN_BACK'},{up='BTN_SIDE'},{up='BTN_BACK'}]").unwrap();
        assert!(compile(bindings.values().next().unwrap()).is_err());
    }

    #[test]
    fn rejects_unsupported_unbalanced_and_invalid_timing() {
        let mut sequence = config::Macro {
            remap: None,
            actions: vec![config::Action {
                at_ms: 0,
                key: KeyCode::KEY_VOLUMEUP,
                pressed: true,
            }],
            duration_ms: 20,
        };
        assert!(compile(&sequence).is_err());
        sequence.actions[0].key = KeyCode::KEY_B;
        assert!(compile(&sequence).is_err());
        sequence.actions.push(config::Action {
            at_ms: 20,
            key: KeyCode::KEY_B,
            pressed: false,
        });
        assert_eq!(compile(&sequence).unwrap().data, vec![1, 5, 0x11, 20, 2, 5]);
        sequence.duration_ms = 19;
        assert!(compile(&sequence).is_err());
        sequence.duration_ms = 300_001;
        assert!(compile(&sequence).is_err());
        sequence.remap = Some(KeyCode::KEY_A);
        assert!(compile(&sequence).is_err());
    }

    #[test]
    fn extended_keys_use_hid_positions() {
        for (key, usage) in [
            (KeyCode::KEY_KPENTER, 0x58),
            (KeyCode::KEY_COMPOSE, 0x65),
            (KeyCode::KEY_KPEQUAL, 0x67),
            (KeyCode::KEY_F24, 0x73),
            (KeyCode::KEY_RIGHTMETA, 0xe7),
        ] {
            assert_eq!(keyboard_usage(key), Some(usage));
        }
    }
}
