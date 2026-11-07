# viktortrilar: viktor/polish
**Goal:** combine the fix list with Eduard's speech work, so the team can build the presentation from main
**Done:** refused moves explain themselves, Delete hides the object's own splats, walls and floor can't be picked, Isolate hides other labels, frames coloured by type, Val talks like a person. Merged Eduard's Whisper mic, viewer actions by voice and safety rules. Added "Val" to the speech hints
**Verified:** 367 tests with the Excel pack, lint clean. Real GPU: 66 of 66 route checks, 28 of 28 combine and delete checks. 6 of 6 voice phrases through a fake mic, with generated speech. Not verified: a real voice, a noisy room, the tablet mic, the viewer checks after the last merge, which timed out, probably on a removed button
**Next:** optimization and bug fixes. Decide on adaptive resolution. Try the mic with a real voice. ElevenLabs test voices need a key from Viktor
**Blockers:** Valmet still has to confirm which pump is P-005. Deadline Sunday 10:00. Roihu closed until at least Monday
