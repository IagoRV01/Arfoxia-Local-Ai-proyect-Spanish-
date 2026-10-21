#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../native/trial_revision.h"
int main(void) {
    char expected[128];
    snprintf(expected,sizeof(expected),"/user/data/Arfoxia/dispatch-v%d.txt",ARFOXIA_TRIAL_REVISION);
    assert(!strcmp(ARFOXIA_TRIAL_LOG,expected));
    snprintf(expected,sizeof(expected),"/user/data/Arfoxia/dispatch-load-v%d.txt",ARFOXIA_TRIAL_REVISION);
    assert(!strcmp(ARFOXIA_TRIAL_LOAD_LOG,expected));
    snprintf(expected,sizeof(expected),"/user/data/Arfoxia/control-v%d.txt",ARFOXIA_TRIAL_REVISION);
    assert(!strcmp(ARFOXIA_TRIAL_CONTROL,expected));
    snprintf(expected,sizeof(expected),"/data/Arfoxia/arfoxia_sprite_candidate_v%d.prx",ARFOXIA_TRIAL_REVISION);
    assert(!strcmp(ARFOXIA_TRIAL_MODULE,expected));
    assert(ARFOXIA_TRIAL_REVISION==10 || ARFOXIA_TRIAL_REVISION==11);
    puts("Compile-time trial paths are isolated and match the reviewed revision");
    return 0;
}
