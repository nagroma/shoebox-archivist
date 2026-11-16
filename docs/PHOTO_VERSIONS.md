# Scan families, scan variants, and keyword sharing

A **scan family** is the set of files for one physical photo or transparency. Each
file is a **scan variant**: for example, an original scan, a corrected front, a back,
or a different resolution scan. Names and keywords remain standard Bridge/Lightroom
metadata in each file. The app does not rename or move the files.

## Configure a library

In **Library → Scan families and filename conventions**:

1. Check **Enable filename conventions for this library** to unlock the controls.
   The **Use Epson FastFoto suggestions** button supplies editable defaults: no suffix = original front, `_a` = corrected
   front, `_b` = back. None of those meanings is fixed; edit suffix, label and role.
2. Choose **Remove a configured suffix**, or **Final number identifies photo**.
   In the latter, `36_Album_0005_a.jpg` has photo identity `36_Album_0005` and
   scan variant `_a`. The entire prefix matters, not just `0005`. A mapped suffix can
   contain digits (for example `_edit2`); unmapped trailing text needs review.
3. Choose the front scan variant to display and the one to use for recognition. If it
   is missing, another front is used. Old detections and decisions remain attached
   to their original files; they are not copied to backs or other variants.
4. **Preview scan families**. Files only match automatically
   within the same folder. Different extensions remain separate physical files.
   Unmapped suffixes/unmatched filenames stay separate, with a review notice.
5. For an exception, choose **Keep separate**, or enter the same scan family name
   on the files to group them explicitly (even across folders). Preview again.
   Clear a manual name to return to filename matching.
6. **Save convention and apply scan families**. This changes app relationships,
   not file metadata. A timestamped SQLite backup is saved beside `library.db`
   before an explicit regroup. App-only metadata differences are shown in the
   preview; the displayed photo keeps its values, other non-empty values fill
   gaps, and original values remain in the backup and per-image history. Faces,
   names, rejections and per-file keyword exceptions are retained.

Imports use the saved convention. A new scan variant joins its existing scan family;
unknown variants remain separate until mapped. Turning off the convention and
using **Pause automatic grouping** leaves existing scan families as they are and stops
applying the convention to future imports.

## Set keyword scope

In **Keywords → Where keywords apply**, add rules for a hierarchy (including its
nested groups) or an exact keyword path. Individual keywords override hierarchy
rules; the closest matching hierarchy wins. No family names are built into rules.

- **All scan variants** is the default, including variants added later. As an
  explicit override it is offered when an inherited rule restricts sharing.
- **Fronts only** / **Backs only** follow the user's configured roles.
- **Keep separate for each scan variant** adds to the displayed file and keeps
  existing locations. Differences in presence across variants are intentional.
- **One scan variant only** allows at most one per scan family. Keyword review
  flags duplicates; choose which variant to keep and confirm before removing any.
- **Choose scan variants by suffix** selects specific suffixes, including no suffix.
  This does not include new suffixes automatically.
- **Ask separately** leaves a scope choice in Keyword review. You can save a rule
  once for that keyword throughout the library, or choose a scope for one scan family.

Without an exception, every keyword applies to all scan variants. For example,
`Attributes|primary` can use **One scan variant only**, while `Attributes|hide`
can use **Keep separate for each scan variant**.
Those are examples, not hardcoded keyword meanings.

On a photo, the scan variant tabs select the physical file. **Keywords across scan variants**
shows the union with a count of variants containing each keyword and an indication
when the keyword belongs to other variants. Metadata below is for the displayed
file. **Keyword sharing for this scan family** can override the inherited scope.
Its individual-file exceptions can keep a keyword present or absent, or restore
inheritance. Exceptions survive later confirmations, imports and rule changes.
Saving a scope/exception is a preference change; it does not itself edit a file.
Removing a keyword from the photo's keyword card explicitly removes it across
variants and keeps absence exceptions so it is not silently restored later.

Confirming a face writes the person's selected keyword(s) according to these
scopes. It does not create face boxes on other variants. An Ask rule records a
pending scope choice instead of arbitrarily choosing a file.

## Review differences

Use **Keywords → Where keywords apply → Review keyword differences for rule violations** to check
saved scan families against your keyword rules. The review leaves intentional
differences alone. **Preview scan families** is only for checking the grouping
and which variants the app will use.

**Keyword review** checks actual metadata, including files changed outside the
app. It distinguishes missing keywords, missing hierarchical paths on flat-only
keywords, keywords outside their selected scope,
deliberate exceptions, pending scope choices, unreadable files and unmapped
scan variants. Imports and folder scans always run a check, including new
variants of existing scan families. The import result links to the review. The nav
badge shows pending items. Saving preferences also runs a check by default; this
can be unchecked. The check does not change photo metadata.

Select individual fixes, or **Select missing keywords**, then **Apply selected
fixes**. Removals are never preselected. Removing an existing owner keyword needs
explicit confirmation. **Keep current value as an exception** preserves a
particular file's current value; exceptions are separately reviewable and can be
returned to inheritance. File write errors are reported individually, and
successful changes remain reflected in the database if another file fails.

Additions write full paths to XMP `lr:hierarchicalSubject` and leaf names to
`dc:subject` and IPTC Keywords where supported by the format. The app records its
additions in `pm:AddedKeywords`; flat field provenance preserves pre-existing
keywords. Explicit owner removals save `pm:Original*` values, so `pm strip` can
restore the pre-app keyword values. Existing legacy app edits continue to use
legacy provenance when per-field tracking is absent.

## Implementation

`backend/variations.py` handles conventions, preview tokens and grouping.
`backend/sharing.py` handles scope inheritance, inventories, exceptions and review.
`image_keywords` is the physical-file inventory; `photo_keywords` is its searchable
photo-level union. `photo_keyword_intents` retains keywords awaiting scope or variants.
Exceptions and photo scopes are anchored to image IDs, so they survive regrouping.
The optional convention and sharing rules are library settings, not photo keywords.

## Choose scan variants in Faces

In **Faces → Scan variants**, choose **Use instead of the original when available**.
The library default follows its recognition variant preference, normally Corrected
front (`_a`) for FastFoto. For each scan family the view uses the chosen file if it
exists; otherwise it shows the original. It does not switch to the original just
because the replacement has no detections. **Also show** includes additional
variants for comparison. Selections are cleared when you change the view, and the
view preference is saved per library. It does not scan more files, alter the
recognition settings, or change which files receive a confirmed person's keywords.
Where a filename convention has not been applied yet, this view can match known
suffixes within the same folder without changing which files are grouped in the library.


**Re-cluster** forms groups using only the scan variants selected in Faces,
including original fallbacks and any variants selected under **Also show**. It
does not change which scans are used for automatic recognition. Changing the
view does not regroup existing clusters; run **Re-cluster** to apply the new
selection. A cluster can still show fewer faces after you name or remove members.
