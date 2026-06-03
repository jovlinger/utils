#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PicoHealth<'a, const N: usize> {
    pub ok: bool,
    pub service: &'static str,
    pub hardware_backend: &'static str,
    pub log_capacity: usize,
    pub log_len: usize,
    pub logs_newest_first: [&'a str; N],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RollingLog<const N: usize> {
    entries: [Option<&'static str>; N],
    next: usize,
    len: usize,
}

impl<const N: usize> Default for RollingLog<N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<const N: usize> RollingLog<N> {
    pub const fn new() -> Self {
        Self {
            entries: [None; N],
            next: 0,
            len: 0,
        }
    }

    pub fn push(&mut self, message: &'static str) {
        if N == 0 {
            return;
        }
        self.entries[self.next] = Some(message);
        self.next = (self.next + 1) % N;
        if self.len < N {
            self.len += 1;
        }
    }

    pub const fn len(&self) -> usize {
        self.len
    }

    pub const fn capacity(&self) -> usize {
        N
    }

    pub fn newest_first<const OUT: usize>(&self) -> [&'static str; OUT] {
        let mut out = [""; OUT];
        if N == 0 || OUT == 0 {
            return out;
        }

        let mut written = 0;
        while written < OUT && written < self.len {
            let newest = (self.next + N - 1 - written) % N;
            out[written] = self.entries[newest].unwrap_or("");
            written += 1;
        }
        out
    }

    pub fn health<const OUT: usize>(&self) -> PicoHealth<'static, OUT> {
        PicoHealth {
            ok: true,
            service: "pico2w-firmware",
            hardware_backend: "pico2w",
            log_capacity: N,
            log_len: self.len,
            logs_newest_first: self.newest_first(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::RollingLog;

    #[test]
    fn rolling_log_returns_newest_first() {
        let mut log: RollingLog<3> = RollingLog::new();

        log.push("one");
        log.push("two");
        log.push("three");
        log.push("four");

        assert_eq!(log.len(), 3);
        assert_eq!(log.capacity(), 3);
        assert_eq!(log.newest_first::<3>(), ["four", "three", "two"]);
    }

    #[test]
    fn health_snapshot_can_be_only_log_payload() {
        let mut log: RollingLog<4> = RollingLog::new();
        log.push("startup");
        log.push("sensor fallback");

        let health = log.health::<2>();

        assert!(health.ok);
        assert_eq!(health.service, "pico2w-firmware");
        assert_eq!(health.logs_newest_first, ["sensor fallback", "startup"]);
    }
}
