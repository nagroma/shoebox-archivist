# Shoebox Archivist — User Guide

Shoebox Archivist helps you name the people in your family photos, date them (even when you only know "about 1950"), and keep it all **inside the photo files**, so other programs like Adobe Bridge or Lightroom see it too.

Open the app at **http://127.0.0.1:8765** after starting it with `uv run pm serve`.
The menu at the top has three pages, **Photos**, **People** and **Faces**, plus the **Add photos** button and **⚙ Settings**.

---

## 1. Adding photos
1. Click **Add photos**.
2. Either:
   - **drop photos** on the box, or click it to choose files (JPG, PNG, TIFF, BMP, WebP). They're copied into your library under `Imported/<today>/`; or
   - click **Scan library folder for new files** if you've copied photos into the library folder yourself.
3. The app reads each photo's existing metadata and looks for faces. You can close the window and keep working.
   - Detection is **thorough** by default: it looks several times (contrast-enhanced, enlarged, rotated) so that tilted, small and faded faces aren't missed. That's several seconds per photo on a CPU, much less with a graphics card.
   - Switch to **Fast** under **Settings** if speed matters more than catching every face.

**What's read from the photo:**
- **Keywords** become chips on the photo. A keyword that matches an existing one is linked to it, e.g. `Mary White` → `People|MaryWhite`. New ones go under *Other Keywords*.
- **Caption, date, location and GPS** fill in the photo's details. A date tagged `unknowndate` is read as "circa" that year.
- **Everything else** (camera, lens, focal length…) is left untouched in the file. You can see it all under **File metadata** on the photo page.

**Photo backs:** name the back scan like the front plus `_b`, `-back` or ` reverse` (e.g. `0012.jpg` + `0012_b.jpg`). The app pairs them automatically.

---

## 2. Photos page
A grid of every photo, with its date and a **named/faces** badge (e.g. `2/3`).

- **Filter** with the tabs: All, Unnamed faces, No date, Has back.
- **Search** keywords, captions, places or file names.
- **Click** a photo to open it.

### Editing many photos at once
1. **Select** photos:
   - **Ctrl-click** (Windows) or **Cmd-click** (Mac), or tick the box in a photo's corner.
   - **Shift-click** selects a range.
   - **Select all** (Ctrl/Cmd+A); **Esc** clears the selection.
2. A panel opens on the right:
   - **Date, Location, Caption** show the value when all selected photos agree. If they differ, the box shows **`<...>`**. Leave it alone to keep each photo's own value, or type to set the same value on all of them.
   - **Keywords** show which selected photos have each one. `3/5` means 3 of the 5 photos; click **+all** to add it to the rest. **×** removes a keyword from all of them. Type in **Add keyword…** to add one to every selected photo.
3. Click **Save to N photos**. The changes are written into the photo files.

---

## 3. A single photo
- **Face boxes** show who's who; the people are listed left to right. Type a name in **Who is this?** for an unnamed face. Accept a suggestion with **✓ Yes**, or reject it with **✗ No** so it won't be suggested again.
- **Details:**
  - **Date** accepts things like `1920s`, `c. 1925`, `May 1923`, `summer 1948` or `1920-1925`.
  - **Location** and **Caption** are free text.
  - The **back** text is for transcribing handwriting.
  - Save with **Ctrl/Cmd+S**.
- **Keywords:**
  - Add from the list, or create a new one in a category.
  - Highlighted keywords were added by this app.
  - Removing a keyword that was already in the file asks first.
- **File metadata** lists every tag stored in the file, read-only.
- **Keyboard:** **←/→** save and move to the previous/next photo; **B** flips to the back scan.

---

## 4. People page
Everyone who appears in your photos, with photo and face counts.

- Tick **Include everyone in the keyword list** to also show people who are in the keyword list but not yet in any photo.
- **+ Add person** creates someone new.
- **Open a person** to:
  - Set **birth/death years**. The app then won't suggest them in photos dated outside their lifetime.
  - Review their **suggested faces**: select the wrong ones, reject them, and confirm the rest.
  - **Name used from** (next to Born/Died): the year the main name came into use. Leave it blank for a name that was always theirs. Example: the main name "Ruth Quill" with *Name used from 1984* and an *Other name* "Ruth Harcourt" (birth) shows Ruth Harcourt on photos dated before 1984 and Ruth Quill after. If the year is unknown, she simply shows as Ruth Quill everywhere.
  - **Notes** are for you only: they stay in the app and are never written to your photo files.
  - Add **Other names** (married name, nickname) with the year each started. The keyword in your files keeps the main name; the app shows the name that fits the photo's date, and typing any of the names finds the person.
  - Fill in the **Family** card: add a person's parents, partners and children (type a name; new people are created). Siblings appear on their own from a shared parent. Everyone connected is then labelled relative to the library's **curator** (Mother/Father, Grandmother/Grandfather, Aunt/Uncle, 1st cousin, Partner's mother/father...), shown on the People cards and the person's page. Set the curator on the **Library** page first.
  - Click **Family tree** to see their family drawn out: parents above, children below, partners side by side. Pick 1-4 generations, click anyone to centre the tree on them, or click **Photos of this family** to list every photo containing someone in that circle. The **Tree** tab shows the curator's tree.
  - On the **Tree** page, **Branch keywords** writes `Family|Quill`, `Family|Harcourt`... into the photos so a family can be searched in Bridge. A person gets the branch of every top ancestor they descend from, so a child of two families has both. A married-in partner keeps their own branch (so Jennifer Driver stays `Quill`). Review the preview, then click **Write branch keywords to photos**. After that first time, naming a person on a photo updates that photo's branch keywords automatically; re-run the button after changing family links. A married-in partner (like a husband outside the curator's family) gets only their own branch; the blood relative gets both. `pm strip` removes them.
  - Choose a **cover** face, **merge** two people who are really the same person, or delete a person.

**Deleting a mistake keyword** (e.g. a stray "Jenni"): if a person was created by mistake, open them and click **Delete person**; their unused keywords go with them. Any other keyword that is on no photo appears under **Library → Unused keywords** with a × to delete it. A keyword that is on photos must first be removed from those photos.

---

## 5. Faces page

**Possible faces** (shown first, when there are any): the app looks hard for faces, including tilted, small and faded ones. That also turns up things that aren't faces, like wheels, lamps or hands.
- Select the real ones and click **✓ Face**, or select the rest and click **✗ Not a face**. With nothing selected, the buttons apply to all of them.
- Nothing is clustered or matched until you've said it's a face.
- **The list learns from your answers.** After about 5 *Not a face* answers, possible faces are sorted most face-like first and tagged **likely face** (green) or **likely not** (red).
  - The *likely not* ones are pre-selected, so often you only need to check them and click **✗ Not a face**. **Select likely not** re-selects them; **Clear** clears the selection.
  - It's only a guess: nothing is hidden or decided without you. Pre-selection can be turned off in **Settings**.

Faces that haven't been confirmed yet, grouped into **clusters** of faces that look alike.

1. Check a cluster. Select any face that doesn't belong and click **Remove from cluster**.
2. Type a name (or pick the suggested one) to name the whole cluster at once.
3. **Ignore** faces not worth naming: strangers, statues, paintings, bad detections. Ignored faces are listed at the bottom and can be restored.

**Strangers, background people, and faces you can't identify** (blurry, turned away, too small): click **Ignore**. Don't create a person like "Unknown" for them.
- Ignored faces are left out of clustering, matching and suggestions, so they stop cluttering the review.
- They stay listed at the bottom of the Faces page, so a wrong call can be **restored** later.
- Ignoring only hides the face from the app's naming; it doesn't change the photo file.
- If someone you *do* know is just hard to see, leave the face unnamed rather than ignored; it can be named later when you have more context.
- A person who matters to the photo but whose name you don't know can be added as a normal person (e.g. "Unidentified man, Grandma's wedding") so you can find those photos later.

**Tips:**
- **Double-click** a face, or click 🔍, to see the whole photo with that face outlined. From there, **Open photo page ↗** jumps to the photo.
- **Re-cluster** regroups the faces after you've named a batch.

---

## 6. Settings
**⚙ Settings** (top right) holds the options that change how the app finds and names faces. They're saved in the library, and the command-line `pm` tool uses them too. A **●** marks a value that's been changed from its default. Click **Save** to apply; **Restore defaults** puts every option back (still needs **Save**).

| Setting | Default | What it does |
|---|---|---|
| **Face detection mode** | Thorough | *Thorough* runs every pass on every photo (about 8× slower, misses fewer faces). *Fast* runs the extra passes only on photos where nothing was found. |
| Contrast-enhanced pass | On | Looks again on a contrast-boosted copy. Helps with faded prints. |
| Enlarged pass | On | Looks again at a larger size. Helps with small faces in group photos. Thorough mode only. |
| Rotated passes | On | Looks again with the photo turned. Finds tilted or lying-down heads. |
| **Suggestion threshold** | 0.35 | How alike a face must be to a known person before their name is suggested. Higher means fewer but safer suggestions. |
| **Name from keywords** | Off | A photo keyworded with one person that shows one face: confirm that face without review. Off, the face is only suggested from the keyword and you confirm in bulk. |
| **Minimum cluster size** | 3 | The smallest group of look-alike faces shown as a cluster on the Faces page. |
| **Pre-select likely non-faces** | On | On the Faces page, pre-select possible faces that look like earlier *Not a face* answers. |

- Detection settings apply to photos scanned **from now on**. To re-check photos already scanned, run `uv run pm ingest <library folder> --rescan`. Existing faces and names are kept.
- Changing the threshold, *Name from keywords* or the cluster size updates suggestions and clusters straight away.
- **About this library** shows the library folder, where the app keeps its database, and whether face detection is using the graphics card (`CUDAExecutionProvider`) or not (`CPUExecutionProvider`).

---

## How the app learns
- When a photo has **one person keyword and one face**, that face is *suggested* from the keyword, and you confirm the suggestions in bulk. Turning on **Name from keywords** in **Settings** skips that review; it is off by default.
- In a photo with several people keywords, faces are matched only against those people. If one face and one name are left over, the name is suggested "by elimination".
- Every name you confirm improves future suggestions. Rejections are remembered too.
- Your **Face / Not a face** answers on possible faces teach the app what a false detection looks like, so later possible faces are sorted and pre-selected for you.

## What the app changes in your files
- **Keywords** you add or confirm, plus the **caption, date and location** you edit.
- The app records what it changed, so it can be undone: `uv run pm strip` removes everything the app added and restores the previous values.
- It never removes keywords that were already in a file unless you confirm.
- It never touches a Lightroom catalog.
