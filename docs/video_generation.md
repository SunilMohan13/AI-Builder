# AeroPulse APAC — hackathon video script

A **2:31** film of **19 narrated clips of 8 seconds** (clips 1–4 are trimmed to 7 s) **plus a 3-second end card**. The live demo is recorded separately and follows the end card. Check 2:31, plus your live demo, against the submission limit. Shorter cuts are in section 8.

How the film is built:

- **Each clip carries its own sound.** The prompt tells Gemini (Veo) to generate:
  - the narrator's exact line, spoken off-screen;
  - the clip's ambient sound (fire, wind, city, interface tones).

  The stitched clips play as a narrated film with no separate voice recording.
- **Same narrator in every clip.** Every prompt uses the identical voice description (section 2). Veo can't reuse a voice across generations, so this keeps the voices close. Section 7 covers what to do if two clips sound different.
- **Every line fits its clip.** Each line has 11–16 words, which is about 5–7 seconds of speech. The narrator starts after a short pause and finishes before the last second. That leaves a quiet tail, so a cut never clips a word.
- **Gemini generates the world, not the product.** Fires, smoke, people and abstract data visuals are generated. Every AeroPulse screen is a **real screenshot or screen recording**, added in the editor (section 5).
- **One main action and one camera move per clip.** Each prompt has the same seven parts: scene, action, camera, style, audio, ending and restrictions.
- **Each prompt is a plain-text copy block.** Paste the whole block into Gemini, one clip per generation. Paste nothing else: the narration, editor text and inserts listed under each block are for you, not for Gemini.
- **Clips chain.** Each clip's ending is the next clip's start. Where the tool supports it, give it the previous clip's **actual last frame** as the first-frame reference (section 7).
- **All labels and figures are added in the editor.** Prompts ask for no on-screen text, because video models distort it. They also ask for **no subtitles**, because some models burn captions in when there is speech.

---

## 1. Story shape

| Part | Clips | Time | The viewer should feel |
| --- | --- | --- | --- |
| Why it matters | 1–4 | 0:00–0:28 | Smoke is real, it travels, and today's AQI can't say what's next |
| The promise | 5–6 | 0:28–0:44 | AeroPulse follows smoke from source to people |
| How it's built | 7–12 | 0:44–1:32 | Honest engineering, region by region |
| What it does | 13–14 | 1:32–1:48 | Where smoke goes, and where it came from |
| Citizens | 15–17 | 1:48–2:12 | People help, and AI is checked, not trusted |
| Product and warning | 18–19 + end card | 2:12–2:31 | One map, an early warning, now watch it live |

AeroPulse is named at about 0:29.

---

## 2. Sound and visual system

### The narrator (identical in every prompt)

> An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says:

Copy this sentence exactly, word for word, into every clip. Changing even one adjective changes the voice. If you prefer a male narrator, swap "female" for "male" in **every** clip before generating any of them.

### Audio rules (in every prompt)

- **The narrator is the only voice.** No on-screen character speaks. Background people are silent or a distant murmur.
- **Pacing:** the narrator starts after about half a second and finishes before the final second. Each line is written to fit, at about 2.2 words per second.
- **Pronunciation:** clips 4, 5, 14 and 19 add a sentence after the quoted line: "AQI" as the letters A-Q-I, and "AeroPulse" as "air-oh-pulse". It sits outside the quotes, so the narrator doesn't read it aloud. If a take still reads it aloud, delete that sentence and regenerate.
- **Only the words inside the quotes are spoken.** Keep the quotation marks when you paste.
- **Ambient sound sits under the voice**, quieter than the narration. Each clip names its own ambient sound.
- **No music in any generated clip.** Music generated per clip changes key and tempo at every cut. If you want music, add one track in the editor, about 20 dB under the narration.

### Two worlds, one geometry

- **Real world** (clips 1–4, 15, the end of 19). Documentary realism: natural light, muted earthy colours, deep navy shadows, warm amber firelight. The only stylisation is a few glowing amber particles inside the smoke.
- **Data world** (clips 5–14, 16–17). Always on the **map stage**: the same composition every time, so the clips read as one film.

> **Map stage:** a dark navy relief map filling the lower two-thirds of the frame, seen from a high three-quarter angle, with a faint cyan hexagon grid and a soft horizon glow in the upper third.

Clip 18 is a real room with a plain screen that you fill in the editor.

### Visual grammar

| Visual | Means | Used in |
| --- | --- | --- |
| Glowing amber particles | Smoke, moving **left to right** with the wind | All smoke shots |
| Soft translucent amber bands, dashed outer edge | **Predicted** transport — never drawn as solid smoke | 13, 19 |
| Cyan dotted trails moving right to left | **Backward trace**: evidence, not a verdict | 14 |
| Hollow rings of different brightness | **Candidate** sources, ranked; never a tick | 14 |
| Cyan lines and hexagons | AeroPulse data | 5–17 |
| Coral glow on a marker | A place in the predicted path | 13, 18, 19 |
| Single coral ripple | A **watch raised** | 17 |
| White pulse | An **independent check passed** (a gate, or a corroborating signal) | 11, 17 |

Never use the white pulse in clips 13 or 14. Prediction and source ranking must not look confirmed.

### Shared prompt lines

Every prompt below already contains these lines.

- **Real-world style:** Photoreal documentary realism, natural light, muted earthy colours, deep navy shadows, warm amber firelight, subtle glowing amber particles inside the smoke. No futuristic interfaces.
- **Data-world style:** The AeroPulse map stage: a dark navy (#0B1426) relief map filling the lower two-thirds of the frame, seen from a high three-quarter angle, with a faint cyan (#22D3EE) hexagon grid and a soft horizon glow in the upper third. Amber (#F59E0B) particles are smoke, cyan is data, coral (#F43F5E) is a place at risk, white is a passed check. Clean, minimal, calm motion.
- **Restrictions:** No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No on-screen character speaks; the narrator is the only voice. No music. No cuts, flashes or explosions.

---

## 3. Timeline

| # | Time | Length | Clip | Generate first? |
| --- | --- | --- | --- | --- |
| 1 | 0:00–0:07 | 7 s | Crop burning, Punjab | **Test batch** |
| 2 | 0:07–0:14 | 7 s | Bushfire, New South Wales | |
| 3 | 0:14–0:21 | 7 s | Peat fire and volcano, Indonesia | |
| 4 | 0:21–0:28 | 7 s | Haze in the city; the phone | |
| 5 | 0:28–0:36 | 8 s | Smoke becomes data | **Test batch** |
| 6 | 0:36–0:44 | 8 s | Five stages | |
| 7 | 0:44–0:52 | 8 s | Data feeds plug in | |
| 8 | 0:52–1:00 | 8 s | 1 km hexagons | |
| 9 | 1:00–1:08 | 8 s | Region packs | |
| 10 | 1:08–1:16 | 8 s | Different winds | |
| 11 | 1:16–1:24 | 8 s | Model gates | |
| 12 | 1:24–1:32 | 8 s | Hourly refresh | |
| 13 | 1:32–1:40 | 8 s | Forward plume | **Test batch** |
| 14 | 1:40–1:48 | 8 s | Backward trace | |
| 15 | 1:48–1:56 | 8 s | A citizen photographs smoke | |
| 16 | 1:56–2:04 | 8 s | Gemini describes the photo | **Test batch** |
| 17 | 2:04–2:12 | 8 s | Independent checks; watch raised | |
| 18 | 2:12–2:20 | 8 s | Command centre and Ask AeroPulse | |
| 19 | 2:20–2:28 | 8 s | Into the town; the warning | **Test batch** |
| End | 2:28–2:31 | 3 s | Earth over APAC, `Live demo →` | Reuses clip 5 |

**How to generate them:**
- Generate every clip at 8 seconds.
- Clips 1–4 have shorter lines that finish by about 6.5 s. Trim each one's quiet last second to keep the opening under 30 seconds.
- Never trim into the narration. If a voice runs to the end of a clip, keep the full 8 s or regenerate.

---

## 4. Clips

### Clip 1 — Crop burning, Punjab (8 s, trimmed to 7 s)

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic documentary video with narration, about crop-residue burning in Punjab, North India.

SCENE: Wide harvested wheat fields at dusk. Small but clearly visible lines of fire burn across the crop stubble. Thick grey-white smoke rises from the fields. A tractor is visible far in the background.

ACTION: The smoke drifts steadily from left to right in the wind.

CAMERA: Begin with a wide aerial view of the burning fields. Slowly push forward and tilt upward to follow the rising smoke, in one continuous, smooth movement.

STYLE: Photoreal documentary realism, natural light, muted earthy colours, deep navy shadows, warm amber firelight, subtle glowing amber particles inside the smoke. No futuristic interfaces. Keep the fire and smoke as the main focus.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Every autumn, North India burns crop stubble. The smoke doesn't stay put." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: the crackle of field fires and a steady wind.

ENDING: A clearly visible smoke column fills the right half of the frame, drifting toward the right edge, with open dusk sky on the left.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No on-screen character speaks; the narrator is the only voice. No music. No cuts, flashes or explosions.
```

**Narration (12 words):** "Every autumn, North India burns crop stubble. The smoke doesn't stay put."

**Editor text:** `Punjab, North India · crop-residue burning`

---

### Clip 2 — Bushfire, New South Wales (8 s, trimmed to 7 s)

**Start from:** clip 1's last frame (smoke column on the right, open sky).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic documentary video with narration, about a bushfire in New South Wales, Australia.

SCENE: A eucalyptus forest ridge on fire. A tall grey-brown smoke column rises from the ridge, with the faint skyline of a distant city on the right horizon under an orange-brown sky.

ACTION: The smoke column leans and drifts from left to right toward the distant city in a hot, dry wind.

CAMERA: One slow pan from left to right along the ridge, following the smoke toward the city.

STYLE: Photoreal documentary realism, natural light, muted earthy colours, deep navy shadows, warm amber firelight, subtle glowing amber particles inside the smoke. No futuristic interfaces.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "In Australia, bushfires lift smoke high above the forest — toward the cities." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a roaring bushfire and gusting wind.

ENDING: The smoke plume leans over the distant city skyline on the right side of the frame.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No on-screen character speaks; the narrator is the only voice. No music. No cuts, flashes or explosions.
```

**Narration (12 words):** "In Australia, bushfires lift smoke high above the forest — toward the cities."

**Editor text:** `New South Wales · bushfire smoke`

---

### Clip 3 — Peat fire and volcano, Indonesia (8 s, trimmed to 7 s)

**Start from:** clip 2's last frame (smoke leaning over a horizon).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic documentary video with narration, about haze over Indonesia.

SCENE: High aerial view of a tropical coastline. On the left, smouldering peatland releases low white-grey smoke between forest and plantations. A volcano on the far horizon vents a grey ash plume. On the right is a calm sea strait.

ACTION: A wide brown-grey haze bank drifts from the land out across the sea, from left to right.

CAMERA: One slow, steady glide to the right, from the coast out over the water.

STYLE: Photoreal documentary realism, natural light, muted earthy colours, deep navy shadows, warm amber firelight, subtle glowing amber particles inside the smoke. No futuristic interfaces.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "In Indonesia, peat fires and volcanoes fill the sky. The haze crosses borders." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: low wind over water and a distant volcanic rumble.

ENDING: The haze bank covers the sea, with a modern city skyline barely visible through it on the right.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No on-screen character speaks; the narrator is the only voice. No music. No cuts, flashes or explosions.
```

**Narration (13 words):** "In Indonesia, peat fires and volcanoes fill the sky. The haze crosses borders."

**Editor text:** `Indonesia · peat fires · volcanic ash` → `haze crosses borders`

---

### Clip 4 — Haze in the city; the phone (8 s, trimmed to 7 s)

**Start from:** clip 3's last frame (a city skyline in haze).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic documentary video with narration, of a city street in smoke haze.

SCENE: A busy Asian city street in thick smoky haze; the sun is a dull orange disc. A person in a face mask stands in the foreground holding a smartphone. The phone screen shows only a plain solid orange circle on a dark background, with empty space below it.

ACTION: The person looks down at the phone, silently; haze drifts left to right past them.

CAMERA: One slow push-in over the person's shoulder until the phone screen fills the centre of the frame.

STYLE: Photoreal documentary realism, natural light, muted earthy colours, deep navy shadows, subtle glowing amber particles in the haze. Shallow depth of field. No futuristic interfaces.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Wind decides who breathes it. AQI shows the air now — not what's next." The narration starts after a brief pause and finishes before the last second. Say "AQI" as the letters A-Q-I. Under the voice, quieter: muffled city traffic and a single distant cough.

ENDING: A close-up of the phone screen: one plain orange circle, centred, with empty dark space below it.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks on the phone or anywhere else. No on-screen character speaks; the narrator is the only voice. No music. No cuts or flashes.
```

**Narration (13 words):** "Wind decides who breathes it. AQI shows the air now — not what's next."

**Editor text:** over the circle, `AQI · now`; below it, fading in one by one, `Where from?` · `Where next?` · `Who to warn?`. Don't add an AQI value. If you want one, take it from a real reading and show its place and time.

---

### Clip 5 — Smoke becomes data (8 s)

**Start from:** clip 4's last frame (the phone close-up with an orange circle).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 video with narration that turns a phone screen into a view of Earth.

SCENE: An extreme close-up of a smartphone screen showing a plain glowing orange circle.

ACTION: The circle dissolves into glowing amber particles that lift off the screen and rise upward, slowly turning from amber to cyan as they climb.

CAMERA: One continuous upward crane that follows the particles up through clouds into space, ending looking down on Earth.

STYLE: Cinematic and photoreal. The night side of Earth over Asia-Pacific, with three soft cyan glows over North India, Singapore and south-east Australia, linked by thin cyan arcs. Colours: deep navy (#0B1426), amber (#F59E0B), cyan (#22D3EE).

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "AeroPulse follows the smoke — from its source, through the wind, to people." The narration starts after a brief pause and finishes before the last second. Say "AeroPulse" as "air-oh-pulse". Under the voice, quieter: a soft rising whoosh that settles into a quiet orbital hum.

ENDING: Earth from orbit, centred on Asia-Pacific, three cyan regions glowing, calm and still. Hold the last second.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (12 words):** "AeroPulse follows the smoke — from its source, through the wind, to people."

**Editor text:** `AeroPulse` and `Source → Wind → People`

**Make one extra take of this clip with no narration** for the end card. Use the same block, but replace the whole line that starts with `AUDIO:` with `AUDIO: A quiet orbital hum only. No voice, no narration.` Save its last 3 seconds.

---

### Clip 6 — Five stages (8 s)

**Start from:** clip 5's last frame (Earth from orbit).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration.

SCENE: The AeroPulse map stage: a dark navy (#0B1426) relief map of Asia-Pacific filling the lower two-thirds of the frame, seen from a high three-quarter angle, with a faint cyan (#22D3EE) hexagon grid and a soft horizon glow in the upper third.

ACTION: Five thin cyan rings appear one after another from left to right, floating in a row above the map, as a thread of amber (#F59E0B) particles flows through them from left to right.

CAMERA: One slow descending push from high above toward the map stage.

STYLE: Amber particles are smoke, cyan is data. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "It observes, understands, predicts, explains and acts — for any region in Asia-Pacific." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: five soft chimes, one as each ring appears.

ENDING: Five glowing empty rings in a row above the map, with the amber thread running through them.

RESTRICTIONS: No on-screen text, letters, numbers, icons, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (12 words):** "It observes, understands, predicts, explains and acts — for any region in Asia-Pacific."

**Editor text:** one word per ring: `Observe` · `Understand` · `Predict` · `Reason` · `Act`

---

### Clip 7 — Data feeds plug in (8 s)

**Start from:** clip 6's last frame (rings above the map stage).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration.

SCENE: The AeroPulse map stage: a dark navy (#0B1426) relief map filling the lower two-thirds of the frame, seen from a high three-quarter angle, with a faint cyan (#22D3EE) hexagon grid. Along the left edge of the map are five hexagonal sockets.

ACTION: Four glowing modules slide in from the left and lock into four of the sockets, one after another, each sending a stream of cyan light across the map. The fifth socket stays empty and dim grey.

CAMERA: Locked-off, with a very slow push-in.

STYLE: Cyan is data. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Ground stations, fire satellites, aerosols and wind forecasts plug in. A missing feed shows as missing." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: four soft mechanical clicks as the modules lock in.

ENDING: Four lit sockets, one dim empty socket, and cyan streams flowing across the map from left to right.

RESTRICTIONS: No on-screen text, letters, numbers, icons, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (16 words):** "Ground stations, fire satellites, aerosols and wind forecasts plug in. A missing feed shows as missing."

**Editor text:**
- one label per lit module: `Ground stations · OpenAQ / NEA` · `Fires · NASA FIRMS` · `Aerosol · Sentinel-5P` · `Weather · Open-Meteo`
- on the dim socket: `not configured — never faked`

**Real insert (optional, 2 s):** the **Data sources** page.

---

### Clip 8 — 1 km hexagons (8 s)

**Start from:** clip 7's last frame (cyan streams across the map stage).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration.

SCENE: The AeroPulse map stage: a dark navy (#0B1426) relief map of a city and its farmland, seen from a high three-quarter angle.

ACTION: Streams of cyan (#22D3EE) particles settle onto the map and snap into a precise honeycomb of small glowing hexagons, spreading in a wave from left to right.

CAMERA: One slow lateral orbit to the right at a constant height.

STYLE: Cyan is data. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Every reading lands on one-kilometre hexagons, labelled measured, modelled or predicted." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a soft cascade, like light rain settling.

ENDING: The whole map is covered by an even grid of softly glowing cyan hexagons.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (11 words):** "Every reading lands on one-kilometre hexagons, labelled measured, modelled or predicted."

**Editor text:** `1 km cells (H3)`, then three small tags: `measured` · `model-derived` · `predicted`

---

### Clip 9 — Region packs (8 s)

**Start from:** clip 8's last frame (a hexagon grid over the map).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration.

SCENE: The AeroPulse map stage: a dark navy (#0B1426) relief map of Asia-Pacific, seen from a high three-quarter angle, with a faint cyan (#22D3EE) hexagon grid. Above it float three translucent glass cards showing simple landscapes: flat farmland plains, a tropical island city with a harbour, and a coastal city with forested hills. A fourth empty glass card hovers at the right.

ACTION: The three landscape cards descend one after another onto the map and dissolve into it. Each lights up its own region in cyan. The empty card stays hovering.

CAMERA: Locked-off, with a very slow push-in.

STYLE: Cyan is data. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Each region is a plug-in pack — its map, hazards and national air-quality scale. No code changes." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: three soft locking sounds.

ENDING: Three regions glowing cyan on the map, and one empty glass card hovering above on the right.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (16 words):** "Each region is a plug-in pack — its map, hazards and national air-quality scale. No code changes."

**Editor text:**
- North India region: `in-north · CPCB scale · crop burning`
- Singapore region: `sg-singapore · NEA scale · transboundary haze`
- NSW region: `au-nsw · NSW categories · bushfire smoke`
- empty card: `next region`

**Real insert (optional, 2 s):** the region switcher in the top bar.

---

### Clip 10 — Different winds (8 s)

**Start from:** clip 9's last frame (three glowing regions).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract weather visualisation with narration.

SCENE: The AeroPulse map stage divided into three equal side-by-side tiles on a dark navy (#0B1426) background: wide flat plains on the left, a small tropical island surrounded by sea in the centre, and dry forested hills on the right.

ACTION: White wind streamlines flow across each tile from left to right, carrying amber (#F59E0B) particles, in visibly different patterns:
- slow and pooling on the plains;
- curling sea breezes around the island;
- fast and gusty over the hills.

CAMERA: Locked-off, with a very slow pull-back to show all three tiles.

STYLE: Amber particles are smoke. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Why not one model for all of Asia-Pacific? Each region breathes a different wind." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: three different wind textures: a low steady breeze, a sea breeze, and hot gusts.

ENDING: All three tiles side by side, each with its own distinct wind pattern.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (14 words):** "Why not one model for all of Asia-Pacific? Each region breathes a different wind."

**Editor text:** `One model per region — not one for all of APAC`; then, under the tiles, `monsoon plains` · `tropical island` · `bushfire country`

---

### Clip 11 — Model gates (8 s)

**Start from:** clip 10's last frame (three tiles).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration.

SCENE: The AeroPulse map stage on a dark navy (#0B1426) background. Three glowing crystal cores sit on the map, one per region, each fed by a river of tiny cyan (#22D3EE) points from the left. Beyond each core stands a simple archway gate.

ACTION: The three cores move toward their gates. Two pass through, and their gates flash a single soft white pulse and stay lit. The third gate stays closed with a dim amber glow, and its core waits in front of it.

CAMERA: Locked-off, with a very slow push-in.

STYLE: Cyan is data; white means a passed check; dim amber means not passed. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Each region learns its own history, and goes live only if it beats a simple baseline." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: two clear soft tones and one muted tone.

ENDING: Two lit gates with cores beyond them, and one closed amber gate with its core waiting.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or bright flashes.
```

**Narration (16 words):** "Each region learns its own history, and goes live only if it beats a simple baseline."

**Editor text:**
- `Trained per region · tested on unseen time and season`
- `Must beat "same as now" · gates are never lowered`
- lit gates: `North India · served` and `Singapore · served`
- closed gate: `NSW · rules, marked degraded`

**Real insert (optional, 2 s):** the **Models** page, showing served versions and evaluation.

---

### Clip 12 — Hourly refresh (8 s)

**Start from:** clip 11's last frame (gates on the map stage).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration.

SCENE: The AeroPulse map stage: a dark navy (#0B1426) relief map filling the lower two-thirds of the frame, seen from a high three-quarter angle, covered with softly glowing cyan (#22D3EE) hexagons in slightly different tints.

ACTION: A thin ring of cyan light sweeps once across the map from left to right like a clock hand. The hexagons refresh their tints as it passes.

CAMERA: Locked-off, with a very slow push-in.

STYLE: Cyan is data. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Every hour, each region's saved model scores the latest data, and the map refreshes." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a soft clock tick, then a gentle data pulse.

ENDING: The refreshed hexagon map, calm. A single bright point glows at the left edge of the map.

RESTRICTIONS: No on-screen text, letters, numbers, clock faces, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or flashes.
```

**Narration (14 words):** "Every hour, each region's saved model scores the latest data, and the map refreshes."

**Editor text:** `Hourly cycle per region · Cloud Run · BigQuery · Cloud Storage` and `every prediction shows its model version`

---

### Clip 13 — Forward plume (8 s)

**Start from:** clip 12's last frame (the map with a bright point on the left).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration, of predicted smoke transport.

SCENE: The AeroPulse map stage: a dark navy (#0B1426) relief map, seen from a high three-quarter angle, with a faint cyan (#22D3EE) hexagon grid. A bright fire point glows on the left. Small round town markers sit across the map to the right.

ACTION: Amber (#F59E0B) particles flow from the fire point to the right along curving wind streamlines. They spread into a fan of soft, translucent amber bands with a dashed outer edge. As the fan reaches each town marker, that marker glows coral (#F43F5E), nearest first.

CAMERA: Locked-off, with a very slow push-in.

STYLE: The plume is soft and translucent, like a probability cloud, not solid smoke. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Simulated particles ride the forecast wind — predicting where the smoke goes, and when it arrives." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a soft whoosh and a gentle ping as each town lights.

ENDING: A translucent amber fan across the map, with three or four coral town markers inside it.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No tick marks or white flashes. No people. The narrator is the only voice. No music. No cuts.
```

**Narration (15 words):** "Simulated particles ride the forecast wind — predicting where the smoke goes, and when it arrives."

**Editor text:** `Predicted smoke transport — experimental` · `200-particle ensemble · P50 / P90 bands`

**Real insert (recommended, 3 s):** a real plume from **Command centre** with the incident panel's arrival list (place and ETA). Use only a Live plume under a Live banner, or a Demo plume with the Demo banner visible. Keep the clip's narration playing under the insert.

---

### Clip 14 — Backward trace (8 s)

**Start from:** clip 13's last frame (the amber fan with coral towns).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract data visualisation with narration, of tracing air backwards.

SCENE: The same AeroPulse map stage: a dark navy (#0B1426) relief map with a faint cyan (#22D3EE) hexagon grid. A ground monitoring station marker on the right glows coral (#F43F5E).

ACTION: Dotted cyan trails stream from the station leftward across the map, against the wind, tracing where the air came from. Three hollow rings appear along the trails, one bright, one medium and one dim.

CAMERA: Locked-off, with a very slow pan to the left following the trails.

STYLE: The trails are dotted and the rings are hollow, to show candidates, not confirmations. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "When a station spikes, AeroPulse traces the air backwards and ranks likely sources — not verdicts." The narration starts after a brief pause and finishes before the last second. Say "AeroPulse" as "air-oh-pulse". Under the voice, quieter: a soft reversed whoosh.

ENDING: Dotted cyan trails across the map, ending at three hollow rings of different brightness on the left.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No tick marks, no white flashes, no solid fills. No people. The narrator is the only voice. No music. No cuts.
```

This is the only clip where motion runs right to left, on purpose: the air is traced backwards in time.

**Narration (15 words):** "When a station spikes, AeroPulse traces the air backwards and ranks likely sources — not verdicts."

**Editor text:** `Likely source region — ranked with evidence, not a percentage`; on the rings, `1` `2` `3`

**Real insert (optional, 2 s):** the source likelihood ranking in an incident panel.

---

### Clip 15 — A citizen photographs smoke (8 s)

**Start from:** cut. This is the move back into the real world. Use a short dissolve from the rings to the smoke.

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic documentary video with narration.

SCENE: Late afternoon on a quiet road at the edge of a town, beside open fields. A young woman holds up her smartphone. In the distance, a grey smoke plume rises from a field and drifts from left to right.

ACTION: She silently takes a photo of the smoke; the phone screen shows the captured image.

CAMERA: One slow push-in over her shoulder to the phone screen.

STYLE: Photoreal documentary realism, natural light, muted earthy colours, deep navy shadows, subtle glowing amber particles inside the smoke. No futuristic interfaces.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Citizens can help: photograph the smoke and send it in. Location is checked; private data removed." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a camera shutter click and light wind.

ENDING: A close-up of the phone screen showing the photo of the smoke plume, centred.

RESTRICTIONS: No on-screen text, letters, numbers, app interface, subtitles, captions, logos or watermarks. The woman does not speak; the narrator is the only voice. No music. No cuts or flashes.
```

**Narration (16 words):** "Citizens can help: photograph the smoke and send it in. Location is checked; private data removed."

**Editor text:** `Citizen report` · `location and time checked · photo metadata stripped`

---

### Clip 16 — Gemini describes the photo (8 s)

**Start from:** clip 15's last frame (the phone screen with the smoke photo).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract visualisation with narration.

SCENE: The photo of a distant smoke plume, as a floating glass card above the AeroPulse map stage: a dark navy (#0B1426) relief map with a faint cyan (#22D3EE) hexagon grid.

ACTION: A soft band of light scans once across the photo card from left to right. Three small blank grey tags attach to its lower edge.

CAMERA: One slow push-in toward the card.

STYLE: The card's outline stays grey: nothing is confirmed yet. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Gemini describes what the photo shows — in words, never numbers. Alone, that proves nothing." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a soft scanning shimmer.

ENDING: The photo card with three blank grey tags, floating in the centre-left of the frame, with empty space on the right.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No tick marks or white flashes. No people. The narrator is the only voice. No music. No cuts.
```

**Narration (14 words):** "Gemini describes what the photo shows — in words, never numbers. Alone, that proves nothing."

**Editor text:**
- on the tags: `smoke plume` · `agricultural field` · `requires corroboration`
- below the card: `AI visual observation`

---

### Clip 17 — Independent checks; watch raised (8 s)

**Start from:** clip 16's last frame (the grey photo card with tags).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9 abstract visualisation with narration.

SCENE: The same photo card with a grey outline, floating centre-left above the AeroPulse map stage. Three dark empty panels wait on the right.

ACTION: The three panels light up one after another, each linking to the card with a thin cyan line and a soft white pulse:
1. a satellite view with a red hotspot dot;
2. white wind arrows pointing from that hotspot toward the card;
3. a small rising bar chart.

Only after the third pulse does the card's outline turn white. A single coral (#F43F5E) ripple then spreads out from the card across the map.

CAMERA: Locked-off, with no movement.

STYLE: White means a passed check; coral means a watch raised. Clean, minimal, calm motion.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Satellite fires, wind and a nearby station must back it up before any watch is raised." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: three soft confirmation tones, then one low alert tone.

ENDING: A white-outlined card, three lit panels, and a fading coral ripple on the map.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No people. The narrator is the only voice. No music. No cuts or bright flashes.
```

**Narration (16 words):** "Satellite fires, wind and a nearby station must back it up before any watch is raised."

**Editor text:**
- on the panels: `FIRMS fire nearby` · `fire upwind` · `PM2.5 rising`
- after the ripple: `corroborated → plume seeded · citizen watch`
- a small side note: `not enough evidence → operator review`
- bottom line: `A citizen photo never creates or changes a pollution event`

**Real insert (recommended, 3 s):** the **Citizen reports** page, showing a report's AI observation and corroboration table.

---

### Clip 18 — Command centre and Ask AeroPulse (8 s)

The product screen is real. Gemini generates only the room, with a plain screen you fill in the editor.

**Start from:** cut, using a short dissolve from the coral ripple.

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic video with narration, of an operations room.

SCENE: A dim, modern operations room. A large wall screen fills the centre of the frame, facing the camera squarely and evenly lit, showing only a plain dark navy (#0B1426) surface with a faint glow. An operator sits in silhouette in the lower-left foreground, with their back to the camera.

ACTION: The operator silently leans slightly toward the screen; soft screen light falls on them.

CAMERA: Straight-on, with a very slow push-in. Keep the screen rectangular and parallel to the frame throughout.

STYLE: Calm, focused, cinematic, with deep navy shadows and soft cyan screen light.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "Operators see one map, and can ask where smoke came from and where it's going." The narration starts after a brief pause and finishes before the last second. Under the voice, quieter: a calm room tone and soft keyboard taps.

ENDING: The same straight-on composition, slightly closer: the operator's silhouette lower-left and the plain glowing screen centred.

RESTRICTIONS: No on-screen text, letters, numbers, interface, map, subtitles, captions, logos or watermarks on the screen or anywhere else. The operator does not speak; the narrator is the only voice. No music. No cuts or flashes.
```

**In the editor:**
1. Place a real **Ask AeroPulse** screen recording on the screen. Ask: "Where is this smoke coming from and where will it go?" Show the cited answer.
2. Over the last 10 frames, cross-fade the screen to a real **Command centre** screenshot: a map with a plume and a place in its path.
3. Export a still of that final composited frame. It is clip 19's starting reference.

**Narration (15 words):** "Operators see one map, and can ask where smoke came from and where it's going."

**Editor text:** `Ask AeroPulse · every figure comes from the data, checked before it is shown`

---

### Clip 19 — Into the town; the warning (8 s)

**Start from:** the composited last frame of clip 18 (the operator, with the Command centre map on the screen).

**Prompt** — copy the whole block into Gemini:

```text
Generate an 8-second, 16:9, cinematic photorealistic video with narration.

SCENE: Starts in a dim operations room: an operator in silhouette lower-left, and a large wall screen centred showing a dark map with a soft amber plume and one coral (#F43F5E) town marker on the right of the map.

ACTION: The coral marker grows as the camera moves toward it, and the screen gives way seamlessly to a real aerial view of that small town in early morning. At a school, a teacher silently closes a classroom window while a thin haze band approaches from the left on the far horizon.

CAMERA: One continuous push forward: into the screen, through the coral marker, and down to the school window.

STYLE: The room is cinematic with navy shadows; the town is photoreal documentary realism with soft morning light. Subtle glowing amber particles in the distant haze.

AUDIO: An off-screen narrator — a calm, warm female voice with a neutral international English accent, mid-pitch, speaking clearly at a calm, steady pace, like a nature documentary — says: "From an AQI number to an early warning. This is AeroPulse — let's see it live." The narration starts after a brief pause and finishes before the last second. Say "AQI" as the letters A-Q-I, and "AeroPulse" as "air-oh-pulse". Under the voice, quieter: room tone fading into morning birdsong.

ENDING: The teacher at the closed window, clear sky overhead, haze on the far horizon on the left.

RESTRICTIONS: No on-screen text, letters, numbers, subtitles, captions, logos or watermarks. No phones showing notifications. No on-screen character speaks; the narrator is the only voice. No music. No cuts or flashes.
```

**If the through-the-screen move doesn't hold:** generate the town part alone, keeping the same `AUDIO:` line. Then match-dissolve in the editor from the coral marker to the school.

**Narration (15 words):** "From an AQI number to an early warning. This is AeroPulse — let's see it live."

**Editor text:** none during the clip.

---

### End card (3 s)

Use the last 3 seconds of the **no-narration take of clip 5**: Earth over Asia-Pacific, with an orbital hum and no voice.
- Add `AeroPulse` and `Source → Wind → People`, then `Live demo →`.
- Fade to navy and silence.
- Start the live demo on the same navy.

---

## 5. Real product footage (record before editing)

Record full screen with the browser chrome hidden. **Live screens must show Live data under the Live banner. If you use Demo, the Demo banner must be visible.** Never show Demo data under a Live banner.

| Use in | Page | Capture |
| --- | --- | --- |
| Clip 7 | Data sources | Connector health, including one `not configured` row if any |
| Clip 9 | Top bar | Switching region between North India, Singapore and NSW |
| Clip 11 | Models | Served version per region, and NSW without a served model |
| Clip 13 | Command centre | A plume with P50 and P90 bands, and the incident panel's place and ETA list |
| Clip 14 | Command centre, incident panel | The likely-source ranking with its evidence |
| Clip 17 | Citizen reports | A report's AI observation ("requires corroboration") and corroboration table |
| Clip 18 | Ask AeroPulse | The question, and a cited answer |
| Clip 18 → 19 | Command centre | A clean map frame with a plume and a place in its path |

Keep each insert to 2–3 seconds, as picture-in-picture or a full-frame cut-away, with the clip's narration still playing underneath. The full walkthrough belongs to the live demo.

---

## 6. Narration script (reference)

This is what the narrator says across the film. Use it to check each generated clip. It is also the script for the fallback in section 7, if you record the voice yourself.

> [1] Every autumn, North India burns crop stubble. The smoke doesn't stay put.
> [2] In Australia, bushfires lift smoke high above the forest — toward the cities.
> [3] In Indonesia, peat fires and volcanoes fill the sky. The haze crosses borders.
> [4] Wind decides who breathes it. AQI shows the air now — not what's next.
> [5] AeroPulse follows the smoke — from its source, through the wind, to people.
> [6] It observes, understands, predicts, explains and acts — for any region in Asia-Pacific.
> [7] Ground stations, fire satellites, aerosols and wind forecasts plug in. A missing feed shows as missing.
> [8] Every reading lands on one-kilometre hexagons, labelled measured, modelled or predicted.
> [9] Each region is a plug-in pack — its map, hazards and national air-quality scale. No code changes.
> [10] Why not one model for all of Asia-Pacific? Each region breathes a different wind.
> [11] Each region learns its own history, and goes live only if it beats a simple baseline.
> [12] Every hour, each region's saved model scores the latest data, and the map refreshes.
> [13] Simulated particles ride the forecast wind — predicting where the smoke goes, and when it arrives.
> [14] When a station spikes, AeroPulse traces the air backwards and ranks likely sources — not verdicts.
> [15] Citizens can help: photograph the smoke and send it in. Location is checked; private data removed.
> [16] Gemini describes what the photo shows — in words, never numbers. Alone, that proves nothing.
> [17] Satellite fires, wind and a nearby station must back it up before any watch is raised.
> [18] Operators see one map, and can ask where smoke came from and where it's going.
> [19] From an AQI number to an early warning. This is AeroPulse — let's see it live.

The bracketed numbers are clip numbers; they are not spoken.

---

## 7. Workflow

### If the generated video has no sound at all

The prompt can't fix this; it's a tool setting.
- **Pick a model that generates audio.** Use a Veo 3-class model. Older or "fast" variants in some tools produce silent video.
- **Turn on audio**, if your tool has a sound or audio toggle.
- **Check the start-frame mode.** In some tools, "frames to video" or image-to-video runs on a model without sound. If a clip made from a start frame comes back silent, generate that clip text-to-video instead. Then line it up with the previous clip in the editor.
- **Check the player.** Play the downloaded file in a desktop player. Some browser previews start muted.

### Generating

1. **Generate the test batch: clips 1, 5, 13, 16 and 19.** Listen for three things:
   - the voice says the exact line;
   - it finishes before the last second;
   - the voice sounds the same across the five clips.

   Fix prompts here before generating the rest.
2. **Lock the look.** Pick one real-world frame (from clip 1) and one map-stage frame (from clip 13). Use them as style references for every clip in the same world, where the tool supports reference images.
3. **Generate in order, chaining frames.** Export each clip's actual last frame and give it to the next clip as the start frame. Make 2–3 takes per clip. Keep the take whose voice and framing best match its neighbours.
4. **Reject any take** where:
   - the narrator changes or skips words;
   - a second voice appears;
   - music is added;
   - subtitles are burned in;
   - the voice is cut off at the end.

   For a skipped or changed word, regenerate. Don't fix it with captions.

### When two clips' voices don't match

Veo can't reuse one voice across separate generations, so some drift is normal. In order of effort:

1. **Regenerate the odd one out** with the identical prompt. The voice description is the same, so another take usually lands closer.
2. **Even out loudness** in the editor: normalise each clip's audio to the same level, around −16 LUFS.
3. **Fallback, for one consistent voice across the whole film:**
   - generate a single narration track with Gemini text-to-speech, or record it yourself, from section 6;
   - lay it over the clips and lower the clips' own audio, so only the ambient sound remains under the new voice;
   - or regenerate the clips with the `AUDIO:` line changed to keep only the ambient sound, ending "No voice, no narration."

### Editing

1. Lay the clips in order. Use straight cuts or 6–8-frame dissolves; clips 15 and 18 open with a dissolve. Trim only the quiet tails.
2. Add editor text and product inserts (section 5). Add captions from section 6, since many judges watch muted.
3. Optionally add one music track, about 20 dB under the narration.
4. Export the composited end frame of clip 18 as clip 19's start reference.

### Before submitting

- **Every line:** heard in full, in the same voice, never cut.
- **Transitions:** every cut matches. The backward trace is the only right-to-left motion.
- **Claims:** every claim is in section 9.
- **Banners:** every product screen has the right Live or Demo banner.
- **Hand-off:** the end card lands on navy and silence, and the live demo starts there.

---

## 8. Length options

| Cut | Drop | Length before the live demo |
| --- | --- | --- |
| Full | — | 2:31 |
| Medium | 6 (five stages), 8 (hexagons), 12 (hourly refresh) | about 2:07 |
| Short | also 14 (backward trace) and 18 (Ask AeroPulse); the live demo shows both | about 1:51 |

Keep clips 1–5 in every cut, so the problem and the promise land by about 0:33.

---

## 9. What every claim rests on

| Claim in the film | Where it is true in the repo |
| --- | --- |
| Three APAC regions, each with its own AQI scale | `config/regions/{in-north,sg-singapore,au-nsw}/region.yaml` (`aqi_standard`: `cpcb_in`, `sg_nea`, `au_nsw_aqc`) |
| Hazards per region (crop burning, transboundary haze, bushfire smoke) | `config/hazard_profiles/*.yaml`, listed under `hazards` in each pack |
| Adding a region needs no code changes | `aeropulse-region init` / `validate`; a test fails if code hardcodes a place |
| Feeds: OpenAQ, NEA, FIRMS, Open-Meteo, Earth Engine (Sentinel-5P) | `connectors/*`; `sources` in each pack |
| A missing feed shows as missing | A missing key means "not configured" and zero records; see the **Data sources** page |
| 1 km hexagons | H3 resolution 8 |
| Readings labelled measured, modelled or predicted | `provenance_class` on every served value |
| One model per region, served only if its gate passed | `config/model_serving.yaml`; `config/models/<region>/<run>/gate.json` |
| Tested on unseen data; no random splits | Gate strategies `purged_rolling_origin` and `season_check` |
| Beats a simple baseline | Served forecasts in `in-north` and `sg-singapore` beat persistence ("same as now") at every horizon from 1 to 24 h |
| NSW runs on rules, marked degraded | `au-nsw` has no entry in `model_serving.yaml` |
| Hourly cycle per region | `aeropulse-cycle --region R`; a Cloud Run Job per region on Google Cloud |
| Simulated particles, P50 / P90 | `libs/intelligence/aeropulse_intelligence/plume/ensemble.py` (`particles: int = 200`) |
| When it arrives (per town) | Plume "reaches" edges to the gazetteer; ETA list in the incident panel |
| Backward trace, ranked sources, no percentages | Backward plume; source likelihood is a heuristic ranking |
| Location checked, private data removed | `apps/citizen_analyzer` sanitize and geo-trust stages |
| Gemini describes in words, never numbers | Schema-constrained AI visual observation; a validator rejects figures; labelled "requires corroboration" |
| Satellite fire, wind and station must back it up | Deterministic corroboration signals; weights in `config/citizen.yaml` |
| Watch raised only when corroborated; otherwise an operator | Decision table: `seed_plume`, `operator_queue`, `stored_operators_only` |
| A citizen photo never creates or changes an event | Hard rule, enforced by tests |
| Ask AeroPulse figures come from the data | Copilot tools and grounding check |

### Do not say or show

- **No accuracy percentages, people-exposed counts, or "X% likely" sources.** Population exposure needs WorldPop data, which no pack has yet. Source likelihood is a ranking.
- **Do not say AeroPulse already tracks volcanoes.** Volcanic ash is in the opening as part of the APAC problem only. There is no volcanic ash hazard profile yet. If asked: a new hazard is a new profile file under `config/hazard_profiles/`.
- **Do not show phone push notifications or SMS.** Alerts are raised each cycle and shown in the Command centre. The cycle hands them to a pluggable alert sink, where SMS or app push would connect later. Clip 19 shows people acting on a warning, not a phone receiving one.
- **Do not say "caused by".** Say "likely source" or "consistent with transport from".
- **Do not make predictions look confirmed.** Use no white pulse in clips 13–14. Label the plume "experimental" and the sources "likely".
- **Do not show Gemini confirming anything.** The card turns white only after the three independent checks in clip 17.
- **Do not add an AQI value or any other figure** unless it comes from a real reading, shown with its place and time.

If you want one hard number on screen, put it in clip 11's editor text: "beats persistence at every horizon from 1 to 24 hours, in North India and Singapore". Read it from the gate reports. Do not round it up.

---

## 10. Hand-off to the live demo

Start the live recording on the same navy and silence as the end card. Then follow the film's order:

1. **Command centre, North India, Live.** The region switcher, the CPCB scale and the Live banner.
2. **Forecast.** The served model version, its band, and the comparison with persistence.
3. **A plume.** P50 and P90 bands, the places it reaches with ETAs, and the "experimental" label.
4. **Evidence.** The incident graph linking fire, wind, plume, station and place.
5. **Switch to Singapore.** A different map, the NEA scale and NEA stations — "no code changes".
6. **Citizen reports.** Upload a photo, then show the AI observation and the corroboration table.
7. **Ask AeroPulse.** "Where is this smoke coming from and where will it go?" Show the cited answer.

If a Live page is empty, show the reason it gives, for example that there are no active events in the window. That is the "never faked" claim from clip 7, shown live.
