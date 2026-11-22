# Three ways to derive cases

Load this file in step 2. Pick per requirement; most requirements need only one of the three.

## 1. Boundaries

Use when the requirement has a limit: a length, a count, an amount, a date, a size, a page number.

For every limit write the value just inside, the value on it, and the value just outside. A range "4 to 12" gives 3, 4, 12 and 13. Two middle values add nothing.

Then look for limits the requirement does not name but the input type has:

| Input | Values worth a case |
|---|---|
| Text | empty, one character, only spaces, the longest allowed, one more than the longest, a character outside ASCII, leading or trailing space |
| Number | zero, negative, the largest allowed, a decimal where a whole number is meant, a number written as text |
| List | empty, one item, two equal items, the largest allowed size |
| Date and time | today, the last day of a month, 29 February, the hour that a clock change skips or repeats, a date in another time zone that is a different day |
| Optional field | absent, present and empty, present and null |
| State | the first use, the second use, use after it expired, use while another request is in flight |

A boundary case is worth keeping only when the spec or the user can say what should happen there. If neither can, it is an open question for the user, not a case.

## 2. Combinations

Use when three or more independent choices meet in one screen or one call (plan, role, region, device, payment method).

1. List each choice as a parameter with its values. Group values the code treats alike into one class and pick one member.
2. Write down combinations that cannot happen as exclusions.
3. Run `pairwise.py`. Its rows contain every pair of values at least once. Most defects that depend on a combination need only two values to meet, so this small set finds most of what the full product would.
4. Add by hand any row with three specific values that the spec calls out, or that failed before. Pairwise does not promise those.

With only two parameters, write all combinations; there is nothing to reduce. With a parameter that changes money, permissions or data loss, consider all combinations for that parameter and say that you did.

## 3. Properties

Use when the code turns one value into another by a rule: a parser, a formatter, a converter, a sort, a price calculation, a merge.

Pick the strongest property that holds, from the top:

| Property | Shape | Example expected result |
|---|---|---|
| Round trip | undo(do(x)) equals x | `decode(encode(x))` returns x for every valid x |
| Reference answer | the fast way equals a slow, obviously right way | total equals the sum computed line by line |
| Unchanged by repeating | f(f(x)) equals f(x) | normalising a normalised phone number changes nothing |
| Something stays fixed | a count, a sum or a set is the same before and after | sorting keeps every item exactly once |
| Order does not matter | the result is the same for any input order | applying two discounts in either order gives one total |
| Never crosses a line | the output stays inside a stated range | the discount is never larger than the cart total |

Write the property as the expected result of one case, with the class of inputs it holds for. Add one or two fixed example cases beside it, so a reader sees a concrete value.

Two ways a property case checks nothing:

- It computes the expected value with the same formula as the code. Then it can only agree.
- Its input class is so narrow that almost no generated value fits it.

"No property fits this code" is a valid outcome. Say so and use boundaries.

## For every case

Before keeping a case, name the fault that would make it fail ("off by one at the upper limit", "expired codes are compared in local time"). A case with no such fault is removed. The count of cases is not a goal.
