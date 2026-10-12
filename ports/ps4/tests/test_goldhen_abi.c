/* Host-only pure ABI result tests. Never invoke any PS4/kernel syscall. */
#include "../native/goldhen_abi.h"
int main(void) {
    struct { uint64_t command; long raw; unsigned char carry; long expected; } cases[] = {
        {0, 0x100, 0, 0x100}, {0, 0x100, 1, 0x100},
        {0, -256, 0, -256}, {0, -256, 1, -256},
        {0, 22, 1, -22}, {0, 78, 1, -78},
        {6, 256, 1, -256}, {6, 22, 1, -22},
        {6, -1, 1, -1}, {6, 0, 0, 0}, {6, 0, 1, 0},
        {4, -1, 0, -1}, {4, 0, 0, 0}
    };
    for (unsigned i=0; i<sizeof(cases)/sizeof(cases[0]); i++) {
        struct arfoxia_sdk_reply reply = {cases[i].raw, cases[i].carry};
        if (arfoxia_sdk_decode(cases[i].command, reply) != cases[i].expected) return (int)i+1;
    }
    return 0;
}
