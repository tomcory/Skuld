You assess whether what a mobile application does with personal data is limited to what its purposes need, from the
context at the end only. The practices (their ids start with P) are what the application was observed to do, with their
components (the practice's id followed by ".data", and for a transmission ".recipient") and the admissible
replacements of the data component: the data nodes the data vocabulary admits as less invasive replacements of its
datum, or none; the purposes (their ids start with H) are those the practice was found to serve, inferred from the
observation, not declared; the screens (ids starting with S) are texts the application showed in the episodes where
the practice occurred; the passages are documentation (ids starting with D) and norms (ids starting with N); the facts
(ids starting with F) each state one property of a datum, quoted from the documentation passage they follow or from
the passage they name; those after the documentation are of the data that could replace the practice's datum.

For each purpose and component, state the less invasive alternatives that would still achieve the purpose. For each,
give:

- "change": what the alternative changes of the component, as one of
  - REMOVE: the component is no longer processed (the datum not collected or sent, the recipient not sent to);
  - REPLACE: the datum is replaced by another, less invasive one; "node" names it by its data node, which must be
    one of the admissible replacements the practice lists for its data component (for example
    device-or-other-ids.app-set-id or location.approximate-location). Where the practice lists none, the datum
    admits no replacement: state only REMOVE, ON_DEVICE or (for a recipient) NARROWER_RECIPIENT;
  - ON_DEVICE: the processing happens on the device, and the data does not leave it;
  - NARROWER_RECIPIENT: the data goes to a recipient of narrower reach (the provider itself rather than a third
    party, fewer recipients).
- "alternative": the alternative in a sentence, for the reader.
- "needs": what the purpose needs, each with an id (N1, N2, …), the requirement in words, and the ids it cites. Read
  what a purpose needs from the screens (S) and the purposes (H) only, never from the practice itself: that the
  application does something is never a reason that it needs to. Name the requirement without naming the data or how
  it is implemented (for example "recognise the same installation on a later launch", not "the advertising ID").
- "gives": what the alternative provides, each a property in words with the ids it cites: the documentation (D) or
  the facts (F) that state it. If no passage or fact of the context states a property, cite "own knowledge".
- "covers": whether what the alternative gives meets what the purpose needs: COVERS (every need is met), PARTLY (some
  are met, or all only in part, so that the purpose is achieved with less quality), DOES_NOT (a need is not met) or
  UNKNOWN; with your reasoning as numbered steps, each citing the context ids it rests on, or "own knowledge" if it
  rests on none.

A need and a property may each have a "kind" and a "value", by which they can be compared:

- scope: the apps among which the same value of an identifier links the user, one of app (one app alone), developer
  (the apps of one developer account on the device), device (every app on the device, though not made to link the
  user across apps) and cross-app (every app on the device, made to link the user across apps and the parties they
  share it with). Each contains the ones before it: app, developer, device, cross-app. For a need, the scope the
  purpose needs; for a property, the identifier's scope.
- persists: the event that ends an identifier's value, one of session (the app's session ends), reinstall (the app is
  uninstalled or its data cleared), reset (the user resets it in the system's settings) and factory-reset (only the
  device's factory reset). Each survives the ones before it: session, reinstall, reset, factory-reset. A fact that
  reads "persists until reset" states that the value lasts until the user resets it, so it survives a reinstall. For a
  need, the earliest event the purpose can let the value end at (a purpose that must recognise a device across
  reinstalls needs reset, since reinstall would end it); for a property, the event that ends it.
- precision_m: a location's precision in metres, a number: how far from the user it may place them. For a need, the
  coarsest precision the purpose can work with; for a property, the location's precision.
- none: the need or property is of none of these kinds.

Give a kind and a value wherever one of these fits, and only then.

Leave out alternatives that would not achieve the purpose, except one you considered and found to leave a need unmet,
which you list with DOES_NOT. If a component admits no less invasive alternative you can state, list no entry for it.

Answer with JSON only, in the form the response schema gives.

The context:

{context}
