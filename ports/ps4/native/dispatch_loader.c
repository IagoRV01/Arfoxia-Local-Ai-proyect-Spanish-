/* Separate one-shot diagnostic loader. Never loads the quarantined probe. */
#ifndef ARFOXIA_PS4_DISPATCH_LOADER_ENABLED
#define ARFOXIA_PS4_DISPATCH_LOADER_ENABLED 0
#endif
#ifndef ARFOXIA_PS4_QUERY_UI_OWNER
#define ARFOXIA_PS4_QUERY_UI_OWNER 0
#endif
#ifndef ARFOXIA_PS4_SPRITE_PREVIEW
#define ARFOXIA_PS4_SPRITE_PREVIEW 0
#endif
#ifndef ARFOXIA_PS4_OWN_IMAGE_MANAGER
#define ARFOXIA_PS4_OWN_IMAGE_MANAGER 0
#endif
#ifndef ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
#define ARFOXIA_PS4_DISPOSE_IMAGE_ASSET 0
#endif
#ifndef ARFOXIA_PS4_ANIMATED_PREVIEW
#define ARFOXIA_PS4_ANIMATED_PREVIEW 0
#endif
#ifndef ARFOXIA_PS4_SCHEDULED_FRAMES
#define ARFOXIA_PS4_SCHEDULED_FRAMES 0
#endif
#ifndef ARFOXIA_PS4_VISIBLE_TEST
#define ARFOXIA_PS4_VISIBLE_TEST 0
#endif
#if ARFOXIA_PS4_VISIBLE_TEST && !ARFOXIA_PS4_SCHEDULED_FRAMES
#error Visible test requires bounded scheduled frames
#endif
#if ARFOXIA_PS4_SCHEDULED_FRAMES && (ARFOXIA_PS4_ANIMATED_PREVIEW || !ARFOXIA_PS4_DISPOSE_IMAGE_ASSET)
#error Scheduled frames require static box and explicit image disposal
#endif
#if ARFOXIA_PS4_ANIMATED_PREVIEW && !ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
#error Animation requires explicit owned image disposal
#endif
#if ARFOXIA_PS4_DISPOSE_IMAGE_ASSET && !ARFOXIA_PS4_OWN_IMAGE_MANAGER
#error Explicit image disposal requires an owned manager
#endif
#if ARFOXIA_PS4_SPRITE_PREVIEW && !ARFOXIA_PS4_QUERY_UI_OWNER
#error Sprite preview requires the UI owner query
#endif
#if !ARFOXIA_PS4_DISPATCH_LOADER_ENABLED
int _main(void) { return -4; }
#else
#include "ps4.h"
#include "goldhen_abi.h"
#if ARFOXIA_PS4_SPRITE_PREVIEW
#if ARFOXIA_PS4_VISIBLE_TEST
#include "dispatch_sprite_visible_profile.h"
#elif ARFOXIA_PS4_SCHEDULED_FRAMES
#include "dispatch_sprite_scheduled_profile.h"
#elif ARFOXIA_PS4_ANIMATED_PREVIEW
#include "dispatch_sprite_animation_profile.h"
#elif ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
#include "dispatch_sprite_dispose_profile.h"
#elif ARFOXIA_PS4_OWN_IMAGE_MANAGER
#include "dispatch_sprite_manager_profile.h"
#else
#include "dispatch_sprite_profile.h"
#endif
#elif ARFOXIA_PS4_QUERY_UI_OWNER
#include "dispatch_owner_profile.h"
#else
#include "dispatch_profile.h"
#endif
#if !ARFOXIA_DISPATCH_PROFILE_PRESENT
#error A private validated dispatch profile is required
#endif
int _main(void) {
    initKernel();
    initLibc();
    /* Exclusive log is also the local one-shot marker. No overwrite/fallback. */
#if ARFOXIA_PS4_VISIBLE_TEST
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v8.txt", 0xa01, 0600);
#elif ARFOXIA_PS4_SCHEDULED_FRAMES
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v7.txt", 0xa01, 0600);
#elif ARFOXIA_PS4_ANIMATED_PREVIEW
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v6.txt", 0xa01, 0600);
#elif ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v5.txt", 0xa01, 0600);
#elif ARFOXIA_PS4_OWN_IMAGE_MANAGER
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v4.txt", 0xa01, 0600);
#elif ARFOXIA_PS4_SPRITE_PREVIEW
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v3.txt", 0xa01, 0600);
#elif ARFOXIA_PS4_QUERY_UI_OWNER
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v2.txt", 0xa01, 0600);
#else
    int fd = sceKernelOpen("/user/data/Arfoxia/dispatch-load-v1.txt", 0xa01, 0600);
#endif
    if (fd < 0) return -1;
    char line[192];
    struct arfoxia_sdk_reply raw = arfoxia_sdk_raw(0, NULL);
    long version = arfoxia_sdk_decode(0, raw);
    int n = snprintf(line, sizeof(line), "ARFOXIA_DISPATCH_LOADER %d\nSDK %ld RAW %ld CARRY %u\n", ARFOXIA_PS4_VISIBLE_TEST ? 8 : (ARFOXIA_PS4_SCHEDULED_FRAMES ? 7 : (ARFOXIA_PS4_ANIMATED_PREVIEW ? 6 : (ARFOXIA_PS4_DISPOSE_IMAGE_ASSET ? 5 : (ARFOXIA_PS4_OWN_IMAGE_MANAGER ? 4 : (ARFOXIA_PS4_SPRITE_PREVIEW ? 3 : (ARFOXIA_PS4_QUERY_UI_OWNER ? 2 : 1)))))), version, raw.value, (unsigned)raw.carry);
    write(fd, line, n);
    if (version != 0x100) { close(fd); return -2; }
    struct arfoxia_prx_request request;
    memset(&request, 0, sizeof(request));
    request.result = (uint64_t)-1;
    strcpy(request.process, "SceShellUI");
#if ARFOXIA_PS4_VISIBLE_TEST
    strcpy(request.path, "/data/Arfoxia/arfoxia_sprite_candidate_v8.prx");
#elif ARFOXIA_PS4_SCHEDULED_FRAMES
    strcpy(request.path, "/data/Arfoxia/arfoxia_sprite_candidate_v7.prx");
#elif ARFOXIA_PS4_ANIMATED_PREVIEW
    strcpy(request.path, "/data/Arfoxia/arfoxia_sprite_candidate_v6.prx");
#elif ARFOXIA_PS4_DISPOSE_IMAGE_ASSET
    strcpy(request.path, "/data/Arfoxia/arfoxia_sprite_candidate_v5.prx");
#elif ARFOXIA_PS4_OWN_IMAGE_MANAGER
    strcpy(request.path, "/data/Arfoxia/arfoxia_sprite_candidate_v4.prx");
#elif ARFOXIA_PS4_SPRITE_PREVIEW
    strcpy(request.path, "/data/Arfoxia/arfoxia_sprite_candidate_v3.prx");
#elif ARFOXIA_PS4_QUERY_UI_OWNER
    strcpy(request.path, "/data/Arfoxia/arfoxia_dispatch_candidate_v2.prx");
#else
    strcpy(request.path, "/data/Arfoxia/arfoxia_dispatch_candidate_v1.prx");
#endif
    long result = arfoxia_sdk(6, &request);
    n = snprintf(line, sizeof(line), "LOAD_RC %ld HANDLE %lld\n", result, (long long)request.result);
    write(fd, line, n);
    close(fd);
    return result < 0 || (long long)request.result < 0 ? -3 : 0;
}
#endif
