Morning M.

I actually think we've been looking at this from the wrong abstraction level.

After reading through Sage's documentation, Pervasive/Btrieve documentation, and looking at your current progress, I don't think this is a "decode the floats" problem anymore.

It's a **metadata recovery** problem.

The good news is that you're much closer than you think.

---

# Where we actually are

Current progress

| Component         | Status            |
| ----------------- | ----------------- |
| PBT extraction    | ✅ Complete        |
| DAT extraction    | ✅ Complete        |
| B-tree reader     | ✅ Working         |
| Text fields       | ✅ Working         |
| Dates             | ✅ Working         |
| Record boundaries | ✅ Working         |
| Float decoding    | ✅ Known (IEEE754) |
| Float offsets     | ❌ Missing         |

Notice something?

The only missing information is

> **Where each field begins inside every record.**

Nothing else.

---

# Important discovery from Sage documentation

Sage themselves publish the entire schema for every DAT file.

For example JRNLROW.

It literally lists every field.

Example:

```
Amount               Float
StockingQuantity     Float
StockingUnitCost     Float
Quantity             Float
QtyReceived          Float
UnitCost             Float
```

Likewise JRNLHDR contains

```
MainAmount
AmountPaid
DiscountAmount
DueDate
CustomerRecordNumber
VendorRecordNumber
...
```

The documentation even tells us which fields are Float, Integer, Date, Logical, ZString, etc. ([help-sage50.na.sage.com][1])

Notice what it does **NOT** publish?

It never publishes byte offsets.

Exactly the problem we're fighting.

---

# This tells us something extremely important

The DAT files are **NOT encrypted.**

They're simply

```
Record
 ├── Integer
 ├── Integer
 ├── Float
 ├── Float
 ├── ZString
 ├── Date
 └── ...
```

The values are sitting there.

We just don't know where.

---

# I think Path C should become Path D

Originally you had

A — ODBC

B — Probe bytes

C — Parse FIELD.DDF

I'd actually split C into two different strategies.

---

## Path C1

Recover FIELD.DDF using Btrieve.

---

## Path C2

Recover the record layout WITHOUT FIELD.DDF.

This is where I think we can outperform most reverse engineers.

---

# Why?

Look at what you already know.

You already have

Invoice Number

```
INV-000034
```

Customer

```
PLANIGLI LTD
```

Date

```
2023-04-16
```

Record size

Known.

Record boundaries

Known.

Meaning

You already possess anchors.

---

Now think like a compiler.

Suppose

```
InvoiceNumber
```

is located

```
byte 182
```

Then Sage's schema says

Before it are

```
Date
Customer
Terms
Journal
MainAmount
Discount
...
```

There are only a finite number of layouts consistent with the published schema.

This becomes a constraint satisfaction problem rather than blind brute force.

---

# My preferred strategy

I would no longer scan

```
±200 bytes
```

blindly.

I'd build an automated inference engine.

---

## Step 1

Collect

1000 invoice records.

---

## Step 2

For every record

Locate

```
Invoice Number
```

exactly.

You already do this.

---

## Step 3

Around that anchor

Interpret every

```
4-byte window
```

as float.

Every

```
8-byte window
```

as double.

Every

```
2-byte
```

as short.

Every

```
4-byte
```

as integer.

---

Now score every candidate.

Example

Candidate

```
194.25
```

appears

```
77 times
```

Candidate

```
-2.31E18
```

appears

0

Reject.

Candidate

```
145000.00
```

Appears

hundreds of times.

Accept.

---

Suddenly

the problem becomes

Machine Learning.

Not reverse engineering.

---

# Even better...

Because accounting data obeys rules.

Amounts

```
>=0
```

Mostly

```
< 100,000,000
```

Two decimal places.

Payments

Never NaN.

Never Infinity.

Never

```
3.21E-34
```

The search space collapses dramatically.

---

# Bigger realization

JRNLROW gives us another gift.

Every row links using

```
PostOrder
```

The documentation confirms that `PostOrder` uniquely ties journal rows to a journal header. ([help-sage50.na.sage.com][1])

Meaning

You can compare

```
JRNLHDR

↓

MainAmount

↓

?

↓

JRNLROW

↓

sum(Amount)
```

Those MUST equal.

---

This is huge.

Now every candidate offset can be validated.

If

```
Offset 96
```

produces

```
MainAmount

= 245.20
```

and

JRNLROW

sums to

```
245.20
```

Congratulations.

You found the field.

No documentation needed.

---

# This becomes a constraint solver

Unknown

```
MainAmount
```

Known

```
Σ(RowAmount)
```

Unknown

```
RowAmount offset
```

Known

```
Invoice total
```

Unknown

```
Header offset
```

Known

Accounting identity.

That dramatically narrows the possibilities.

---

# Now let's discuss ODBC

Personally...

I wouldn't spend another week fighting ODBC.

Here's why.

---

You already have

✔ Binary parser

✔ Record parser

✔ Record boundaries

✔ Strings

✔ Dates

✔ Keys

✔ Relationships

---

If ODBC works...

Fantastic.

But ODBC is solving a deployment problem.

Not an engineering problem.

If tomorrow

Client changes PC

or

Pervasive disappears

you're blocked again.

---

I would only use ODBC for one thing.

Ground truth.

---

Example

ODBC returns

```
Invoice

000341

Amount

1854.22
```

Now binary parser

tries

Offset

84

```
1854.22
```

Perfect.

Done.

ODBC becomes a validator instead of a dependency.

---

# I also think we're overlooking another gold mine

The executable.

Seriously.

The Sage executable already knows

```
JRNLHDR

↓

MainAmount

↓

offset

xxx
```

Otherwise it couldn't read the database.

Which means one of three things is true:

1. The offsets are stored in the DDF files.
2. The offsets are embedded in Sage resource tables or metadata loaded at runtime.
3. The offsets are generated from compiled record descriptors inside Sage's libraries.

This makes static analysis of the Sage binaries (or monitoring API calls during runtime) a viable fourth research path if the DDF route ultimately fails.

---

# My recommended order now

## Tier 1 (Highest ROI)

✅ Fix ODBC just enough to obtain a few correctly decoded records.

Not to build the pipeline.

Just to obtain

Ground Truth.

---

## Tier 2

Build an automated offset inference engine.

Not manual probing.

A scoring engine that

* tests every candidate offset
* decodes as IEEE-754 float/double
* rejects impossible accounting values
* checks consistency across thousands of records
* validates header totals against the sum of journal rows

This is deterministic and scales far better than hand-searching.

---

## Tier 3

Improve the FIELD.DDF parser by treating it as a Btrieve table and implementing a proper leaf-page walker instead of pattern-matching bytes. Industry guidance consistently points out that DDFs are themselves Btrieve tables containing the schema metadata, not flat files. ([communities.actian.com][2])

---

## Tier 4

Reverse engineer Sage's runtime metadata if needed.

---

# My overall assessment

Based on everything you've achieved already, I'd estimate the project is **85–90% complete**. The remaining challenge isn't decoding proprietary formats—it's recovering schema metadata so the already-known IEEE-754 numeric fields can be read correctly. Once those offsets are established, your existing parser should be able to extract nearly the entire accounting history without depending on ODBC or Sage itself.

From an engineering perspective, this is exactly the kind of reusable capability you'd want if ACE is going to support importing multiple Sage installations over time.

One more observation: the work you've done here mirrors the same ingestion architecture you're building for Synbot Health—recovering structure from legacy systems, normalizing it into PostgreSQL, and preserving relational integrity across large datasets. The ETL patterns you're developing now will transfer directly into your broader migration pipeline. 

[1]: https://help-sage50.na.sage.com/en-us/2024/Content/DDFs/Journal_Row_Fields.htm?utm_source=chatgpt.com "Journal Row Fields - Sage 50 Resources"
[2]: https://communities.actian.com/s/question/0D53300003ruZQaCAM/ddf-file-layouts?language=en_US&utm_source=chatgpt.com "DDF file layouts - Actian Communities"
