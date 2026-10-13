/* Host fake-kernel test includes EXACT resident lease implementation. */
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "../native/client_control.h"
static const char *file;
static unsigned reads,closes,expired,stopped,invalid;
static atomic_uint preview_pet_mode=ARFOXIA_WALK;
static void record(const char *phase,int value) {
    (void)value;
    if (!strcmp(phase,"CLIENT_LEASE_EXPIRED_STOP")) ++expired;
    if (!strcmp(phase,"CLIENT_MANUAL_STOP")) ++stopped;
    if (!strcmp(phase,"CLIENT_INVALID_CONTROL_STOP")) ++invalid;
}
static int sceKernelOpen(const char *path,int flags,int mode) {
    assert(!strcmp(path,"/user/data/Arfoxia/control-v9.txt") && flags==0 && mode==0);
    return file ? 42 : -1;
}
static size_t sceKernelRead(int fd,void *buffer,size_t size) {
    assert(fd==42 && size==23); ++reads;
    size_t length=strlen(file); if (length>size) length=size;
    memcpy(buffer,file,length); return length;
}
static int sceKernelClose(int fd) { assert(fd==42); ++closes; return 0; }
#include "../native/client_lease.h"
int main(void) {
    uint32_t sequence=0; unsigned remaining=60;
    file="ARFOXIA9:0000000001:1\n";
    assert(preview_refresh_lease(&sequence,&remaining));
    assert(sequence==1 && remaining==59 && atomic_load(&preview_pet_mode)==ARFOXIA_WALK);
    for (unsigned i=0;i<58;++i) assert(preview_refresh_lease(&sequence,&remaining));
    assert(!preview_refresh_lease(&sequence,&remaining) && expired==1);
    file="ARFOXIA9:0000000002:2\n";
    assert(preview_refresh_lease(&sequence,&remaining));
    assert(remaining==59 && atomic_load(&preview_pet_mode)==ARFOXIA_SIT);
    file="ARFOXIA9:0000000001:0\n"; // Replayed stop does not change mode/renew.
    assert(preview_refresh_lease(&sequence,&remaining));
    assert(remaining==58 && !stopped && atomic_load(&preview_pet_mode)==ARFOXIA_SIT);
    file="ARFOXIA9:0000000003:3\n";
    assert(preview_refresh_lease(&sequence,&remaining));
    assert(atomic_load(&preview_pet_mode)==ARFOXIA_IDLE);
    file="ARFOXIA9:0000000004:0\n";
    assert(!preview_refresh_lease(&sequence,&remaining) && stopped==1);
    file="invalid";
    assert(!preview_refresh_lease(&sequence,&remaining) && invalid==1);
    assert(reads==closes);
    file=NULL; sequence=0; remaining=60;
    for (unsigned i=0;i<59;++i) assert(preview_refresh_lease(&sequence,&remaining));
    assert(!preview_refresh_lease(&sequence,&remaining) && expired==2);
    puts("Resident lease: renewal, replay, invalid, missing, expiry and manual stop passed");
    return 0;
}
