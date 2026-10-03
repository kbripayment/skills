# Date-driven inspection-photo retrieval from Gmail

For "find the 검수사진 / inspection photo for these transaction
statement dates" tasks. Use when the item description on the statement
is too generic for product-token matching (e.g. the statement line is
just "표준가스" / a vendor category, not a product name).

## Why this path exists

The normal `find_inspection_photo_for_statement()` path scores candidate
mails by matching statement *item tokens* against OCR/Vision text in the
attachment. A statement whose only line item is a generic category
(표준가스, 시약, 소모품) produces tokens that appear on half the
mailbox, so nothing scores as reliable and the search returns zero.
When the item hint is generic, do not loosen the scorer — sweep by date.

## Procedure

1. **Get the candidate date list from the user, not from OCR.** A
   scanned statement's stamp date is frequently unreadable (Tesseract
   turns `2026` into `2024`/`2036`; Vision returns 4-5 different
   answers for the same page across crops). Ask which dates are
   candidates, and treat the user's list as authoritative — including
   explicit exclusions ("9/10 is wrong"). If the user retracts a date,
   delete the already-saved file for it, don't just stop using it.

2. **Sweep the sender by date window, then match the subject exactly.**

   ```python
   q = (f"from:{SENDER} after:{d-timedelta(days=2)} "
        f"before:{d+timedelta(days=3)} has:attachment")
   ```

   The ±window is only to catch mails sent the evening after the
   inspection. **Selection must be on the subject prefix**, never on the
   window — neighbouring dates land in each other's windows:

   ```python
   label = f"{d.month}/{d.day}"          # "7/9", NOT "07/09"
   sel = [m for m in msgs if m.subject.strip().startswith(label + " 검수사진")]
   ```

   Subject form is `N/M 검수사진 송부`. Zero-padded or `YYYY-MM-DD`
   subject forms exist too, so normalise both sides before comparing.

3. **Download every image attachment of the selected mails.** A single
   date often has 2-3 mails (morning + afternoon) and 1-3 images each;
   take all of them and let the content filter decide. See the Gmail
   attachment section of SKILL.md for the payload walk and the `id=`
   parameter.

4. **Downscale before Vision, every time.**

   ```python
   im = Image.open(path).convert("RGB")
   if max(im.size) > 1200:
       im.thumbnail((1100, 1100))
   im.save(out, quality=85)
   ```

   Phone-camera originals arrive at 4128×3096 or 5712×4284 and
   `vision_analyze` returns `Request timed out` on them. 1100px /
   q85 is ~150KB and classifies fine. Montaging does not rescue this:
   2-up 640px cells and 4-up 900px montages both timed out repeatedly
   while individual 1100px files succeeded. **Per-file at ≤1100px is
   the only reliable batch shape** — batch with parallel tool calls,
   not with bigger images.

   Also: derive the small-copy filename with `os.path.splitext` on the
   basename, not by string-concatenating the original extension —
   `foo.jpeg` becomes `foo.jpeg.jpg` otherwise and the path won't load.

5. **One yes/no question per image.** Ask "is this a metal gas
   cylinder? what is the label text?" — a single classification plus
   the readable label. A four-way montage prompt asking for a table of
   per-cell verdicts produces confident prose about the wrong cell when
   the layout is ambiguous.

6. **Save only positives, named for the date.** Copy the *original*
   download, not the downscaled copy, and name it
   `YYYYMMDD_<kind>_<identifier>.jpg` in Korean
   (e.g. `20260709_가스용기_질소.jpg`). Write a `_수집결과.md` next to
   them listing per-date: saved file, one-line description, and the
   excluded images with what they actually were.

7. **Report coverage, not just totals.** Say which candidate dates are
   covered and which images were rejected as unrelated goods, and flag
   any two saved images that look like the same cylinder photographed
   on adjacent dates — that usually means a date or a duplicate delivery
   and is worth a human glance.

## Pitfalls

- A `±N`-day Gmail window alone silently returns the neighbouring
  date's mail. Match the subject prefix; the window is a fetch
  optimisation only.
- Do not treat OCR of a stamp date as authoritative. Ask for the
  candidate list, and when several Vision reads of the same crop
  disagree, report the disagreement and move on rather than escalating
  through more crops.
- `2026-09-10` style exceptions: when a date is retracted, remove the
  already-saved artefact so the folder does not keep a photo the user
  rejected.
