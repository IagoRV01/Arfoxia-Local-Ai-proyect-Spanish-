/* Compile-time isolation for the same bounded experiment, never a reload. */
#ifndef ARFOXIA_TRIAL_REVISION_H
#define ARFOXIA_TRIAL_REVISION_H
#ifndef ARFOXIA_TRIAL_REVISION
#define ARFOXIA_TRIAL_REVISION 10
#endif
#if ARFOXIA_TRIAL_REVISION != 10 && ARFOXIA_TRIAL_REVISION != 11
#error Only separately reviewed trial revisions are supported
#endif
#define ARFOXIA_TEXT_INNER(value) #value
#define ARFOXIA_TEXT(value) ARFOXIA_TEXT_INNER(value)
#define ARFOXIA_TRIAL_LOG "/user/data/Arfoxia/dispatch-v" ARFOXIA_TEXT(ARFOXIA_TRIAL_REVISION) ".txt"
#define ARFOXIA_TRIAL_LOAD_LOG "/user/data/Arfoxia/dispatch-load-v" ARFOXIA_TEXT(ARFOXIA_TRIAL_REVISION) ".txt"
#define ARFOXIA_TRIAL_CONTROL "/user/data/Arfoxia/control-v" ARFOXIA_TEXT(ARFOXIA_TRIAL_REVISION) ".txt"
#define ARFOXIA_TRIAL_MODULE "/data/Arfoxia/arfoxia_sprite_candidate_v" ARFOXIA_TEXT(ARFOXIA_TRIAL_REVISION) ".prx"
#endif
