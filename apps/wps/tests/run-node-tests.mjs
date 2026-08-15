// WPS Node tests canonical entry.
//
// CI and apps/wps/scripts/verify.ps1 both run this single entry so the list
// of mandatory WPS Node regression tests lives in exactly one place.
// Importing a missing test file fails the run (node fails fast) — a missing
// mandatory test must never be silently skipped.

import "./host-runtime.test.mjs";
import "./taskpane-runtime.test.mjs";
import "./reader-ui.test.mjs";
import "./format-settings.test.mjs";
