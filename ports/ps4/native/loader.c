/* Raw BinLoader payload: only load Arfoxia's diagnostic PRX into SceShellUI. */
#include "ps4.h"
#include "goldhen_abi.h"
int _main(void) {
    initKernel();
    initLibc();
    int fd = sceKernelOpen("/data/Arfoxia/load.txt", O_WRONLY|O_CREAT|O_TRUNC, 0600);
    if (fd < 0) return -1;
    char line[256];
    long version = arfoxia_sdk(0, NULL);
    int n = snprintf(line, sizeof(line), "ARFOXIA_LOADER 1\nSDK %ld\n", version);
    write(fd, line, n);
    if (version != 0x100) { close(fd); return -2; }
    struct arfoxia_prx_request request;
    memset(&request, 0, sizeof(request));
    request.result = (uint64_t)-1;
    strcpy(request.process, "SceShellUI");
    strcpy(request.path, "/data/Arfoxia/arfoxia_probe.prx");
    long result = arfoxia_sdk(6, &request);
    n = snprintf(line, sizeof(line), "LOAD_RC %ld HANDLE %lld\n", result, (long long)request.result);
    write(fd, line, n);
    close(fd);
    return result < 0 || (long long)request.result < 0 ? -3 : 0;
}
