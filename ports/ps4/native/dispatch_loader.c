/* Separate one-shot diagnostic loader. Never loads the quarantined probe. */
#ifndef ARFOXIA_PS4_DISPATCH_LOADER_ENABLED
#define ARFOXIA_PS4_DISPATCH_LOADER_ENABLED 0
#endif
#if !ARFOXIA_PS4_DISPATCH_LOADER_ENABLED
int _main(void) { return -4; }
#else
#include "ps4.h"
#include "goldhen_abi.h"
#include "dispatch_profile.h"
#if !ARFOXIA_DISPATCH_PROFILE_PRESENT
#error A private validated dispatch profile is required
#endif
int _main(void) {
    initKernel();
    initLibc();
    /* Exclusive log is also the local one-shot marker. No overwrite/fallback. */
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v1.txt", 0xa01, 0600);
    if (fd < 0) return -1;
    char line[192];
    struct arfoxia_sdk_reply raw = arfoxia_sdk_raw(0, NULL);
    long version = arfoxia_sdk_decode(0, raw);
    int n = snprintf(line, sizeof(line), "ARFOXIA_DISPATCH_LOADER 1\nSDK %ld RAW %ld CARRY %u\n", version, raw.value, (unsigned)raw.carry);
    write(fd, line, n);
    if (version != 0x100) { close(fd); return -2; }
    struct arfoxia_prx_request request;
    memset(&request, 0, sizeof(request));
    request.result = (uint64_t)-1;
    strcpy(request.process, "SceShellUI");
    strcpy(request.path, "/data/Arfoxia/arfoxia_dispatch_candidate_v1.prx");
    long result = arfoxia_sdk(6, &request);
    n = snprintf(line, sizeof(line), "LOAD_RC %ld HANDLE %lld\n", result, (long long)request.result);
    write(fd, line, n);
    close(fd);
    return result < 0 || (long long)request.result < 0 ? -3 : 0;
}
#endif
