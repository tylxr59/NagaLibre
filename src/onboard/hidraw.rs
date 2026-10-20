//! Linux hidraw feature reports; no kernel-driver detaching or firmware upload.
use super::{Identity, Mouse, Transport};
use anyhow::{Context, Result, bail, ensure};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io,
    os::fd::AsRawFd,
    path::Path,
    thread,
    time::{Duration, Instant},
};

const SIZE: usize = 91;

/// A checksum-valid, transaction/command-matched firmware rejection. Callers
/// must not mistake transport timeouts or malformed packets for unsupported data.
#[derive(Debug)]
pub struct Rejected {
    pub class: u8,
    pub command: u8,
    pub status: u8,
}

impl std::fmt::Display for Rejected {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "Mouse rejected {:02x}/{:02x}: status {:#x}",
            self.class, self.command, self.status
        )
    }
}
impl std::error::Error for Rejected {}

fn ioctl_code(direction: u32, number: u32, size: usize) -> libc::c_ulong {
    ((direction << 30) | ((size as u32) << 16) | (u32::from(b'H') << 8) | number) as libc::c_ulong
}

pub fn request(transaction: u8, class: u8, command: u8, payload: &[u8]) -> Result<[u8; SIZE]> {
    ensure!(payload.len() <= 80, "Feature payload too long");
    let mut buffer = [0; SIZE];
    buffer[2] = transaction;
    buffer[6] = payload.len() as u8;
    buffer[7] = class;
    buffer[8] = command;
    buffer[9..9 + payload.len()].copy_from_slice(payload);
    buffer[89] = buffer[3..89].iter().fold(0, |crc, byte| crc ^ byte);
    Ok(buffer)
}

fn reply(request: &[u8; SIZE], response: &[u8; SIZE], echo: usize) -> Result<Option<Vec<u8>>> {
    if response[0] != 0 || response[2] != request[2] || response[7..9] != request[7..9] {
        return Ok(None);
    }
    if response[1] <= 1 {
        return Ok(None);
    }
    if response[89] != response[3..89].iter().fold(0, |crc, byte| crc ^ byte) {
        return Ok(None);
    }
    if response[1] != 2 {
        return Err(Rejected {
            class: request[7],
            command: request[8],
            status: response[1],
        }
        .into());
    }
    let length = usize::from(response[6]);
    ensure!(
        length <= 80 && echo <= length && echo <= usize::from(request[6]),
        "Invalid feature response length"
    );
    if response[9..9 + echo] != request[9..9 + echo] {
        return Ok(None);
    }
    Ok(Some(response[9..9 + length].to_vec()))
}

/// Show transport metadata, and only a validated mapping-address echo. Never
/// include action data, serial payloads or a whole feature report in errors.
fn timeout_details(request: &[u8; SIZE], response: &[u8; SIZE]) -> String {
    let checksum_ok = response[89] == response[3..89].iter().fold(0, |crc, byte| crc ^ byte);
    let mut details = format!(
        "last response: report {}, status {:#04x}, transaction {:#04x}, command {:02x}/{:02x}, length {}, checksum {}",
        response[0],
        response[1],
        response[2],
        response[7],
        response[8],
        response[6],
        if checksum_ok { "valid" } else { "invalid" }
    );
    if request[7..9] == [2, 0x8c]
        && response[0] == 0
        && response[1] == 2
        && response[2] == request[2]
        && response[7..9] == request[7..9]
        && (3..=80).contains(&response[6])
        && checksum_ok
    {
        details.push_str(&format!(
            "; mapping echo: slot {}, wire button {:#04x}, layer {}",
            response[9], response[10], response[11]
        ));
    }
    details
}

/// Recognize the report-ID-zero, 90-byte feature collection used by this mouse.
/// HID globals can be stacked and a report may consist of multiple main items.
fn control_descriptor(bytes: &[u8]) -> Result<bool> {
    let (mut size, mut count, mut id) = (0u32, 0u32, 0u32);
    let mut stack = Vec::new();
    let mut feature_bits = BTreeMap::<u32, u32>::new();
    let mut at = 0;
    while at < bytes.len() {
        let prefix = bytes[at];
        at += 1;
        if prefix == 0xfe {
            ensure!(at + 2 <= bytes.len(), "Truncated long HID item");
            let length = usize::from(bytes[at]);
            at += 2;
            ensure!(at + length <= bytes.len(), "Truncated long HID payload");
            at += length;
            continue;
        }
        let length = match prefix & 3 {
            3 => 4,
            n => usize::from(n),
        };
        ensure!(at + length <= bytes.len(), "Truncated HID descriptor");
        let mut value = 0u32;
        for (shift, byte) in bytes[at..at + length].iter().enumerate() {
            value |= u32::from(*byte) << (8 * shift);
        }
        at += length;
        match ((prefix >> 2) & 3, prefix >> 4) {
            (1, 7) => size = value,
            (1, 8) => id = value,
            (1, 9) => count = value,
            (1, 10) => stack.push((size, count, id)),
            (1, 11) => {
                (size, count, id) = stack.pop().context("Unbalanced HID global stack")?;
            }
            (0, 11) => {
                let bits = size
                    .checked_mul(count)
                    .context("Invalid HID feature size")?;
                let total = feature_bits.entry(id).or_default();
                *total = total
                    .checked_add(bits)
                    .context("HID feature size overflow")?;
            }
            _ => {}
        }
    }
    Ok(feature_bits.get(&0) == Some(&720))
}

#[repr(C)]
struct RawInfo {
    bus: u32,
    vendor: i16,
    product: i16,
}

pub struct Hidraw {
    file: File,
    identity: Identity,
}

impl Hidraw {
    fn open(path: &Path, product: u16, descriptor: &[u8]) -> Result<Self> {
        ensure!(
            control_descriptor(descriptor)?,
            "Not a Naga feature-report interface"
        );
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .with_context(|| {
                format!(
                    "Opening {}; mouse access needs elevated permissions",
                    path.display()
                )
            })?;
        let mut info = RawInfo {
            bus: 0,
            vendor: 0,
            product: 0,
        };
        // SAFETY: RawInfo is repr(C), the request encodes its exact size, and fd is live.
        let result = unsafe {
            libc::ioctl(
                file.as_raw_fd(),
                ioctl_code(2, 3, std::mem::size_of::<RawInfo>()) as _,
                &mut info,
            )
        };
        if result < 0 {
            return Err(io::Error::last_os_error()).context("Reading hidraw identity");
        }
        ensure!(
            info.bus == 3
                && info.vendor as u16 == 0x1532
                && info.product as u16 == product
                && matches!(product, 0xa7 | 0xa8),
            "Unexpected hardware identity"
        );
        Ok(Self {
            file,
            identity: Identity {
                path: path.display().to_string(),
                product,
                serial: String::new(),
            },
        })
    }
}

impl Transport for Hidraw {
    fn identity(&self) -> Identity {
        self.identity.clone()
    }
    fn exchange(&mut self, class: u8, command: u8, payload: &[u8], echo: usize) -> Result<Vec<u8>> {
        let mut packet = request(0x1f, class, command, payload)?;
        // SAFETY: packet is exactly SIZE bytes; the ioctl request carries SIZE.
        let length = unsafe {
            libc::ioctl(
                self.file.as_raw_fd(),
                ioctl_code(3, 6, SIZE) as _,
                packet.as_mut_ptr(),
            )
        };
        if length < 0 {
            return Err(io::Error::last_os_error()).context("Sending feature report");
        }
        ensure!(
            length == SIZE as i32,
            "Short feature write: {length}/{SIZE} bytes"
        );
        let deadline = Instant::now() + Duration::from_millis(1000);
        loop {
            thread::sleep(Duration::from_millis(30));
            let mut response = [0; SIZE];
            // SAFETY: response is exactly SIZE bytes and remains live for the call.
            let length = unsafe {
                libc::ioctl(
                    self.file.as_raw_fd(),
                    ioctl_code(3, 7, SIZE) as _,
                    response.as_mut_ptr(),
                )
            };
            ensure!(
                length == SIZE as i32,
                "Reading feature report failed: {}",
                io::Error::last_os_error()
            );
            if let Some(data) = reply(&packet, &response, echo)? {
                return Ok(data);
            }
            if Instant::now() >= deadline {
                bail!(
                    "No matching reply to mouse command {class:02x}/{command:02x}; {}",
                    timeout_details(&packet, &response)
                );
            }
        }
    }
}

pub fn connect() -> Result<Mouse<Hidraw>> {
    let mut candidates = Vec::new();
    for entry in fs::read_dir("/sys/class/hidraw").context("No hidraw devices found")? {
        let entry = entry?;
        let device = entry.path().join("device");
        let properties = fs::read_to_string(device.join("uevent")).unwrap_or_default();
        let Some(id) = properties
            .lines()
            .find_map(|line| line.strip_prefix("HID_ID="))
        else {
            continue;
        };
        let parts: Vec<_> = id.split(':').collect();
        if parts.len() != 3 || u32::from_str_radix(parts[1], 16).ok() != Some(0x1532) {
            continue;
        }
        let Ok(product) = u16::from_str_radix(parts[2].trim_start_matches('0'), 16) else {
            continue;
        };
        if !matches!(product, 0xa7 | 0xa8) {
            continue;
        }
        let descriptor =
            fs::read(device.join("report_descriptor")).context("Reading mouse HID descriptor")?;
        if control_descriptor(&descriptor)? {
            candidates.push((
                product,
                Path::new("/dev").join(entry.file_name()),
                descriptor,
            ));
        }
    }
    candidates.sort_by_key(|(product, path, _)| (*product, path.clone()));
    ensure!(
        !candidates.is_empty(),
        "No Naga V2 Pro control interface found. Connect it by USB cable or its 2.4 GHz receiver; Bluetooth is not supported for onboard writes."
    );
    let preferred = candidates[0].0;
    ensure!(
        candidates
            .iter()
            .filter(|(pid, _, _)| *pid == preferred)
            .count()
            == 1,
        "Multiple Naga control interfaces found. Connect one mouse while editing onboard memory."
    );
    let mut errors = Vec::new();
    for (product, path, descriptor) in candidates {
        let result = (|| -> Result<_> {
            let mut transport = Hidraw::open(&path, product, &descriptor)?;
            let mode = transport.exchange(0, 0x84, &[0; 2], 0)?;
            ensure!(mode.len() == 2, "Unexpected device-mode reply");
            Ok(Mouse { transport })
        })();
        match result {
            Ok(mouse) => return Ok(mouse),
            Err(e) => errors.push(format!("{}: {e:#}", path.display())),
        }
    }
    bail!(
        "Could not read the mouse control interface: {}",
        errors.join("; ")
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn inventory_reply_uses_reported_length_instead_of_request_size() {
        let packet = request(0x1f, 5, 0x81, &[0; 6]).unwrap();
        let mut response = packet;
        response[1] = 2;
        response[6] = 3;
        response[9..12].copy_from_slice(&[5, 1, 2]);
        response[89] = response[3..89].iter().fold(0, |a, b| a ^ b);
        assert_eq!(reply(&packet, &response, 0).unwrap(), Some(vec![5, 1, 2]));
    }

    #[test]
    fn feature_framing_and_reply_checks_reject_stale_or_corrupt_data() {
        let packet = request(0x1f, 2, 0x8c, &[1, 0x40, 0, 0, 0, 0, 0, 0, 0, 0]).unwrap();
        assert_eq!(ioctl_code(3, 6, 91), 0xc05b4806);
        assert_eq!(
            &packet[..12],
            &[0, 0, 0x1f, 0, 0, 0, 10, 2, 0x8c, 1, 0x40, 0]
        );
        let mut response = packet;
        response[1] = 2;
        response[12] = 2;
        response[13] = 2;
        response[14] = 0;
        response[15] = 5;
        response[89] = response[3..89].iter().fold(0, |a, b| a ^ b);
        assert_eq!(
            reply(&packet, &response, 3).unwrap().unwrap()[3..7],
            [2, 2, 0, 5]
        );
        response[10] = 0x41;
        response[89] = response[3..89].iter().fold(0, |a, b| a ^ b);
        assert!(reply(&packet, &response, 3).unwrap().is_none());
        response[10] = 0x40;
        assert!(reply(&packet, &response, 3).unwrap().is_none());
    }
    #[test]
    fn timeout_metadata_exposes_wrong_bank_echo_but_never_private_payloads() {
        let packet = request(0x1f, 2, 0x8c, &[1, 0x40, 1, 0, 0, 0, 0, 0, 0, 0]).unwrap();
        let mut response = packet;
        response[1] = 2;
        response[11] = 0;
        response[12..18].copy_from_slice(b"SECRET");
        response[89] = response[3..89].iter().fold(0, |a, b| a ^ b);
        assert!(reply(&packet, &response, 3).unwrap().is_none());
        let details = timeout_details(&packet, &response);
        assert!(details.contains("mapping echo: slot 1, wire button 0x40, layer 0"));
        assert!(!details.contains("SECRET"));
        response[89] ^= 1;
        let details = timeout_details(&packet, &response);
        assert!(details.contains("checksum invalid"));
        assert!(!details.contains("mapping echo"));
        let serial = request(0x1f, 0, 0x82, b"SECRET").unwrap();
        assert!(!timeout_details(&serial, &serial).contains("SECRET"));
        assert!(!timeout_details(&serial, &serial).contains("mapping echo"));
    }

    #[test]
    fn descriptor_requires_exact_feature_shape_and_handles_push_pop() {
        assert!(control_descriptor(&[0x75, 8, 0x95, 90, 0xb1, 2]).unwrap());
        assert!(!control_descriptor(&[0x85, 1, 0x75, 8, 0x95, 90, 0xb1, 2]).unwrap());
        assert!(!control_descriptor(&[0x75, 8, 0x95, 90, 0x81, 2]).unwrap());
        assert!(control_descriptor(&[0x75, 8, 0x95, 90, 0xa4, 0x95, 1, 0xb4, 0xb1, 2]).unwrap());
        assert!(control_descriptor(&[0x75]).is_err());
    }
}
