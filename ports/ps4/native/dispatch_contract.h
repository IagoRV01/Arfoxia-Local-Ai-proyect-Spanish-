/* Pure bounded guards, host-testable; no Mono, syscalls or console access. */
#ifndef ARFOXIA_DISPATCH_CONTRACT_H
#define ARFOXIA_DISPATCH_CONTRACT_H
static inline int arfoxia_guid_equal(const char *actual, const char *expected) {
    if (!actual || !expected) return 0;
    for (unsigned i = 0; i < 36; ++i) {
        unsigned char a = (unsigned char)actual[i], b = (unsigned char)expected[i];
        if (!a || !b) return 0;
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (a != '-' || b != '-') return 0;
        } else {
            if (a >= 'a' && a <= 'f') a -= 'a' - 'A';
            if (b >= 'a' && b <= 'f') b -= 'a' - 'A';
            if (!((a >= '0' && a <= '9') || (a >= 'A' && a <= 'F')) || a != b) return 0;
        }
    }
    return actual[36] == 0 && expected[36] == 0;
}
#endif
