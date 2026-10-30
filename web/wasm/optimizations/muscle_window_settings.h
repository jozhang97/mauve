#ifndef MAUVE_MUSCLE_WINDOW_SETTINGS_H
#define MAUVE_MUSCLE_WINDOW_SETTINGS_H
#include <functional>
namespace muscle {
// Copy parameter values, never scratch buffers or per-thread cache pointers.
std::function<void()> mauve_muscle_settings_snapshot();
}
#endif
