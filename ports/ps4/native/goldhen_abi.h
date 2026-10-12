/* Minimal published GoldHEN SDK ABI; no kernel offsets or memory writes.
 * ABI reference: GoldHEN/GoldHEN_Plugins_SDK, include/GoldHEN.h (MIT).
 */
#ifndef ARFOXIA_GOLDHEN_ABI_H
#define ARFOXIA_GOLDHEN_ABI_H
#include <stdint.h>
struct arfoxia_prx_request {
    char process[32];
    char path[100];
    uint64_t result;
} __attribute__((packed));
_Static_assert(sizeof(struct arfoxia_prx_request) == 140, "GoldHEN PRX ABI");
struct arfoxia_process_info {
    int pid;
    char name[40], path[64], title_id[16], content_id[64], version[6];
    uint64_t base_address;
} __attribute__((packed));
_Static_assert(sizeof(struct arfoxia_process_info) == 202, "GoldHEN process ABI");
static inline long arfoxia_sdk(uint64_t command, void *data) {
    long result = 500;
    unsigned char failed;
    __asm__ volatile("syscall; setc %1"
        : "+a"(result), "=m"(failed)
        : "D"(command), "S"(data)
        : "rcx", "r11", "memory");
    return failed ? -result : result;
}
#endif
