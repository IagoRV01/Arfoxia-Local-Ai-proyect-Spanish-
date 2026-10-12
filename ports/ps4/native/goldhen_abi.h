/* Minimal published GoldHEN SDK ABI; no kernel offsets or memory writes.
 * ABI reference: GoldHEN/GoldHEN_Plugins_SDK, include/GoldHEN.h (MIT).
 */
#ifndef ARFOXIA_GOLDHEN_ABI_H
#define ARFOXIA_GOLDHEN_ABI_H
#include <stdint.h>
/* CE-36329-3 during Mono metadata enumeration on 12.52. Keep ALL native
 * entry points disabled until an independently validated replacement exists.
 */
#define ARFOXIA_PS4_PROBE_QUARANTINED 1
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
struct arfoxia_sdk_reply { long value; unsigned char carry; };
static inline struct arfoxia_sdk_reply arfoxia_sdk_raw(uint64_t command, void *data) {
    /* Match GoldHEN's published orbis_syscall: indirect syscall(0), with
     * SDK number 500 as its first argument. A direct RAX=500 is not that ABI.
     */
    long result = 0;
    unsigned char failed;
    __asm__ volatile("syscall; setc %1"
        : "+a"(result), "=m"(failed)
        : "D"((uint64_t)500), "S"(command), "d"(data)
        : "rcx", "r11", "memory", "cc");
    return (struct arfoxia_sdk_reply){result, failed};
}
static inline long arfoxia_sdk_decode(uint64_t command, struct arfoxia_sdk_reply reply) {
    /* Accept only the exact SDK version signature, never arbitrary errors.
     * Record raw value/carry in the loader to diagnose firmware ABI differences.
     */
    if (command == 0 && reply.value == 0x100) return reply.value;
    return reply.carry && reply.value > 0 ? -reply.value : reply.value;
}
static inline long arfoxia_sdk(uint64_t command, void *data) {
    return arfoxia_sdk_decode(command, arfoxia_sdk_raw(command, data));
}
#endif
