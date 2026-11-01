# release

### 1.0.0

- prepared base and luxe packages, each with optional auto arm shield
- finalized loader metadata, update URL and versioned ZIP names

# pre-release

<details>
<summary>development history</summary>

### 0.4: release preparation

**0.4.0**

- fixed hidden printer-tooltip hover for Small Battery and Oxygen Tank
- test builds:
  - `INGAME test.1`: slots, printing, save/reload, death recovery, vehicles, catalog and multiplayer with both models and Shield options
  - `hover-fix.1`: private hover previews and toggle stability; crash found
  - `hover-fix.2`: battery/tank hover, recipe changes, cleanup and independent local/multiplayer tooltip settings
  - `compatibility.1`: shared ZIP imports in Vortex and AML-Classic; representative variant coverage

### 0.3: luxe model & refinements

**0.3.4**

- removed hidden faces while preserving shading; retained the simplified rear panel
- rebuilt battery accent mounts and simplified the blue inset; restored original band and eyelet detail
- cleaned build scripts and retired comparison code
- test builds:
  - `test.1`: rear UV continuity and lower-detail left bands/eyelets
  - `test.2`: rebuilt mounts, simpler blue inset and restored band/eyelet detail on both models
  - `test.3`: taller Base accent assembly and continuous mount UVs

**0.3.3**

- refined palette mapping, shading and shoulder details
- adjusted battery fit, drone socket and front border
- test builds:
  - `test.1`: rear mapping, drone socket fit, stripe, engraving and power icon
  - `test.2`: UV precision, rear alignment and separate pad materials
  - `test.3`: pad/battery mapping and drone socket clearance
  - `test.4`: pad-face visibility and two distorted rear-side polygons
  - `test.5`: front-base/pad patterns, blue band, wider gold stripe and joined casing shading
  - `test.6`: flat octagonal settings and two-triangle battery-arrow shading
  - `test.7`: casing smoothing, battery fit, pad joins, emblem seating and rear mapping on both models
  - `test.8`: battery contact without inner bevels; moon, border and stripe smoothing comparison
  - `test.9`: divider diameter, top-eyelet mapping and left morse smoothing
  - `test.10`: star/moon shapes, morse smoothing and trimmed bands; rounded settings and gold-join comparison
  - `test.11`: native casing joins, raised stripe, simplified casings, settings, borders and palette mapping
  - `test.12`: front-side closure and edited supports, casings and front base
  - `test.13`: front alignment, battery fit, tube eyelets and matching setting-shell smoothing
  - `test.14`: oxygen-cap palette, housing UV continuity and hidden-face removal coverage

**0.3.2**

- added glow to decorations, morse and power icon; reduced morse polygons
- refined gold finish, engraving and oxygen-band UVs
- added gold stripe around the back and sides
- test builds:
  - `test.1`: glow, decoration thickness and simpler morse shapes
  - `test.2`: glow colours and engraving without rectangular outline
  - `test.3`: lower glow brightness and deeper engraving
  - `test.4`: rounded engraving, morse glow and shinier gold
  - `test.5`: power icon, wider engraving bevel and morse finishes
  - `test.6`: glowing-gold finishes and power-icon placement
  - `test.7`: selected gold finish, flat power accent, oxygen-band UVs and simpler left morse
  - `test.8`: taller accent, back/side stripe coverage and simpler right morse
  - `test.9`: stripe alignment with blue band and thicker power icon

**0.3.1**

- refined luxe pads, settings, decoration thickness and oxygen supports
- added Y.U.E. engraving and morse
- changed gold colour and corrected AML filenames
- test builds:
  - `test.1`: trim proportions, decoration thickness and shoulders
  - `test.2`: engraving, morse, pad borders and oxygen-support fit

**0.3.0**

- added luxe model, gold decorations and shoulder rings
- refined shapes, finishes and shoulder movement; worked on catalog startup
- corrected ZIP filenames from `3.0.0` to `0.3.0`; contents retain original labels
- test builds:
  - initial build: first luxe model in game
  - `test.1`: gold finishes on right pads
  - `test.2`: satin vs champagne gold
  - `test.3`: decoration shapes and shoulder-ring movement
  - `test.4`: catalog startup position
  - `test.5`: moon/star shapes, shine and elbow-decoration rotation
  - `test.6`: pad rows, raised diamonds, palette-coloured up marker and hologram hover
  - `test.7`: hover, catalog startup after appearance setup and shinier diamonds
  - `test.8`: catalog pose settling within a limited retry window after rendering
  - `test.9`: remote catalog startup on late joins and delayed first views
  - `test.10`: deferred catalog startup and delayed palette setup; startup crash
  - `test.11`: startup stability with corrected palette-function reference
  - `test.12`: catalog startup completion after animation
  - `test.13`: simpler catalog startup using animation completion

### 0.2: auto arm shield & tooltip toggle

**0.2.5**

- extended auto-arm shield to carried generators, portable smelters, small printers and jetpacks
- enabled printer-tooltip hover while toggled off
- test builds:
  - `test.1`: auto-arm protection for carried equipment slots
  - `test.2`: printer-tooltip hover while toggled off

**0.2.4**

- kept custom backpack parts visible in vehicle mode

**0.2.3**

- added optional auto-arm blocker, including protection against feeding carried snails
- reduced printer info-icon size and ongoing palette, drone socket and catalog checks
- cleaned code and prepared luxe build options
- test builds:
  - `test.1`: auto-arm blocker and smaller info-icon readability
  - `test.2`: palette/drone updates and catalog behaviour without repeating checks
  - `test.3`: callback cleanup after backpack removal/replacement and all-feature ZIP

**0.2.2**

- saved printer-tooltip preference between sessions

**0.2.1**

- replaced eye icon with info icon; added separate hide/show sounds
- fixed catalog-control clipping and mission-log position
- test builds:
  - `test.1`: info-icon readability, toggle sounds and catalog startup
  - `test.2`: catalog-handle startup position
  - `test.3`: catalog/mission-log positions after closing
  - `test.4`: revised catalog-handle reset
  - `test.5`: faster catalog-handle reset
  - `test.6`: vanilla closed-pose alignment and late opening-animation suppression

**0.2.0**

- added printer-tooltip toggle button; fixed icon flashing and added sound
- test builds:
  - initial test: printer-tooltip toggle
  - `test.2`: tooltip-icon flashing and revised eye artwork
  - `test.3`: displayed eye icon and button sound

### 0.1: base model development

**0.1.12**

- renamed mod to Backpack Pro Max and set main items to 80% size
- cleaned code and finished base model

**0.1.11**

- updated catalog clipping fix and tried 75% item size

**0.1.10**

- fixed drone socket visibility and made it Creative-only
- added catalog clipping fix
- changed lower battery accent to trim colour and tried 70% item size

**0.1.9**

- applied edited front base and battery shapes/positions
- updated tubing openings and drone socket palette fix

**0.1.8**

- simplified pads, tubing and batteries
- added supports, backing and tubing eyelets; removed battery side borders
- reduced items to 80% size
- added separate drone socket visual sharing backpack colours

**0.1.7**

- refined front edge, battery casings and trim colours
- added battery side borders and lower accent

**0.1.6**

- removed dependency on original Backpack16 mod
- added smooth front, paired pads, rails and battery casings
- restored vanilla item size and control positions

**0.1.5**

- switched to vanilla-style meshes/materials for palette matching
- adjusted item size and death-backpack slots

**0.1.4**

- corrected socket colours, adjusted battery supports and addressed cyan printer speck

**0.1.3**

- made battery shallower; adjusted shell, side panels and drone slot
- tried different materials for speckled surfaces

**0.1.2**

- corrected surface rendering and overlapping socket rings
- restored upper-backpack details and adjusted handle clearance

**0.1.1**

- fixed startup crash

**0.1.0**

- first compact 16-slot prototype with custom front and slimmer battery

</details>
