# Inspection-photo retrieval

Covers: finding the photos that belong to a given transaction statement, and filtering a
batch down to the object the user actually asked for.

## When the automated finder returns nothing

`quote_tax_invoice_photo.py` matches inspection mail against the statement's **item tokens**.
A statement whose item is a utility or service (`표준가스`, 세금, 전기) has tokens that never
appear in the mail body, so the matcher reports 0 photos even when the photos exist.

Fall back to direct Gmail search rather than forcing the matcher:

| Goal | Query |
|---|---|
| All inspection mail in range | `from:checker@example.com has:attachment after:YYYY/MM/DD before:YYYY/MM/DD` |
| One exact date (preferred) | `from:checker@example.com after:D-2 before:D+3 has:attachment` → keep subjects starting `N/M 검수사진` |
| Narrow by supplier | `(<supplier> OR "<supplier>" OR <item>) has:attachment after:... before:...` |
| Narrow by a known date | `from:checker@example.com has:attachment after:YYYY/MM/DD before:YYYY/MM/DD+1` |

Inspection mail volume is ~100–130 messages over a six-month span, so fetching all metadata
is cheap; the expensive step is downloading and viewing attachments.

## Exact-subject date keying (prefer this over stamp OCR)

The stamp-date section below describes fighting ambiguity. There is a much cheaper key that
should be tried first: **the inspection mail's own subject states the date.**

Subjects are `N/M 검수사진 송부` (`1/2 검수사진` has no space; tolerate either). So for a
target date D:

```
from:<sender> after:D-2 before:D+3 has:attachment
```

then keep only messages whose subject starts with `N/M 검수사진` for that exact D. The
`after/before` window is only a cheap prefilter — on its own it returns up to 7 mails
(D-2 … D+2), one or two per day, so the subject prefix is what actually pins the date.

Why this matters: a batch can run several mails on the same date (morning + afternoon),
and the day either side may also contain photos. Filtering by subject keeps every mail
belonging to the target date and drops both the neighbours and the wrong-day duplicates.

Attachment filenames usually embed the same date (`20260709_150237.jpg`,
`[크기변환]20260901_130357.jpg`) and are a cheap cross-check that the subject filter worked.
One mail may carry a filename from the previous day (a batch uploaded the evening before)
— that is a retrieval artefact, not a date conflict; trust the subject, and note it.

If the user supplies a **list** of candidate dates, run this filter once per date and
collect the union. In the Korean research-purchasing case this replaced a stamp-date
escalation that had gone unresolved across an entire prior session: the stamp read as a
different date on every pass, but the subjects answered all 16 dates in one pass.

## Multi-date statements: one deliverable, one page per date

A statement can span several transactions, each page carrying its own stamp date (`9/22`
B-27 on page 1, `9/28` antibody on page 2). The filename then names only one of them
(`..._B27외_...`), so the filename is a hint about one page, never a bound on the file's
contents.

The retrieval key is **per stamp date**, not per file. Run the exact-subject date filter once
for every date found, union the candidates, then filter by object per date — the two dates
share a supplier and a mail batch but not a single item.

Deliverable shape: one PDF, one A4 portrait page per date, each captioned with its date and
the item it evidences. Add the date as visible text on the page (`page.insert_text` with an
explicit Korean font buffer) because the source photos carry no visible date stamp. When the
user asked for one file covering the statement, a single-date PDF reads as an incomplete
answer even though every page in it is correct.

**Check whether the pipeline already does this.** The integrated downloader threads
`inspection_dates` into the inspection finder and wraps the candidate downloader so any
stamp date not yet searched is searched on the first call, with a `searched_dates` set
suppressing duplicates. A run log line naming every stamp date in the search key
(`검수일: 2026-09-22, 2026-09-28 기준으로 …`) is the proof it worked. Grep for
`inspection_dates` / `items_by_date` and read the run log before reporting a gap — a
requirement filed against already-implemented behaviour sends the next session to re-fix a
working path.

## Object-level filtering is mandatory

A single inspection mail routinely carries several unrelated items. A gas-supplier search still
returns culture media and consumables from other orders in the same batch. Subject lines and
body text do not determine what is in the photo.

For every candidate attachment:

1. Download it
2. Open it with vision and ask one narrow question — *is object X present?*
3. Keep positives, record negatives with the reason

Report both sets. Presenting a filtered set as if it were the whole deliverable hides that
filtering happened, and presenting everything buries the answer.

Useful discriminators on gas cylinders: cylindrical steel body, shoulder taper, brass valve
with hand wheel, protective cap, 2-wheel transport cart, `Ar`/`O2`/`N2` stencilling, ISO 5149
marking, 위험도 2.2 diamond. Reagent bottles that superficially resemble them are white
screw-cap plastic, not valve-fitted steel.

## Date keying from handwritten stamps

When the user wants photos for a specific stamp date, that date is the matching key. Scanned
transaction statements have no text layer, so the date must be read from the image.

Reliable escalation:

1. Crop the date field at ~400–700 dpi, run `--psm 4` / `--psm 11`
2. If the digits stay ambiguous, use vision on a tight per-page crop
3. Cross-check two or three times

**Stop condition.** If the same field yields different readings on successive passes, the
digit is unresolved, not merely blurry. Distinguishing symptoms in Korean business handwriting:

- `7` read as `1`
- `8` read as `4` or `2`
- `2026` read as `2024` / `2036` / `2046`

Mounting many pages into one montage is a candidate-generation aid only — a montage reading
that disagrees with a single-page reading means the montage is not usable as a matching key.

When the stop condition hits, deliver the date-keyed candidate photos and ask which page's date
applies, naming the pages. Do not keep re-cropping.

## Saving

Land candidates in a folder marked as provisional (`_후보` suffix or similar) until the date
key is confirmed, then keep only the matching subset. Write a short status file next to the
candidates listing what was excluded and what is still blocked.

Once the date key IS confirmed, drop the `_후보` marker — a confirmed set left in a
provisional folder reads as unfinished. Delete superseded candidates whose date turned out
to be wrong rather than leaving them beside the good set.

## Assembling a deliverable PDF

When the user asks for the retrieved images collected into one file, build a real PDF with
PyMuPDF: one A4 portrait page per image, filename-derived caption (`[nn/N] M/D — 판별요약`),
`page.insert_font(fontname=..., fontfile=...)` with `malgun.ttf`/`malgunbd.ttf` for Korean,
image aspect-fitted inside a margin box, page number and source filename in the footer.

Two things worth knowing:

- **Korean text needs an explicit font buffer.** `page.insert_text(..., fontname="malgb")`
  alone raises `ValueError: need font file or buffer`. Call `page.insert_font()` with
  `fontfile` first, on every page, then reference that name.
- **File size is dominated by outliers.** A set mixing 1000px and 4128px originals lands
  around 35MB, because four phone-resolution images carry most of the weight. Offer to
  re-sample to ~2000px when the user needs an email- or print-friendly file; do not silently
  downscale originals that were requested as evidence.
