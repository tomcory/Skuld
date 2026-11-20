You prepare an experiment on an Android application. An automated explorer used the app and carried out a flow, a feature of the app; you are given what the explorer was asked to do, its verifier's reading of what happened, and the screens of the app from the flow's start to its end. Your task is to say what kind of feature this is, what it is for, and how to recognise from the screens that a later repetition of the flow achieved it.

A flow may carry out more than one feature: a first run whose onboarding ends at the app's main feature (a forecast, a feed, a map), say, carries out both the onboarding and that feature, whose outcome the last screen shows. Give each feature the flow carries out to its outcome, the one the last screen shows first, at most three.

# The catalogue

Kinds of features that apps share are kept as feature families. Each has a description, its purposes, and slots: values to be taken from this flow's screens so that its success can be checked.

{catalogue}

If one of these families describes a feature, answer with its id and fill each of its slots. Otherwise answer "new" and describe a new family in `new_family`: general enough for other apps to have the same kind of feature (no app names, no texts of this app), specific enough that its purposes fit every feature of the kind.

# A new family

- `id`: lower-case words joined by hyphens, e.g. `email-sign-up`, `nearby-search`, `workout-recording`.
- `entry`, `path`, `outcome`: where such a feature starts, what the user does, and what they see when it worked, in words, for any app.
- `purposes`: what the feature is for, each as action, object, beneficiary (`user`, or `provider` where the feature serves the app's provider), context and outcome, with the node of the purpose vocabulary it falls under (one of: {nodes}), whether the node fits it exactly or is broader (`fit`), and its role: `functional` if it is what the user does the feature for, `ancillary` otherwise.
- `requirements`: per purpose, the capabilities the purpose needs, stated without naming the data or the technique that might provide them. Write "determine an area relevant to the user", not "obtain the user's GPS coordinates"; "recognise the returning user", not "read the device ID". Name no personal data, identifier, permission or service.
- `oracle`: per purpose, how to recognise from the screens that the purpose was achieved, or null where the screens cannot show it (e.g. the purpose is achieved on the provider's servers). An oracle is a list of conditions that must all hold, each a check with one slot:
  - `text_shown`: the screen at the end of the flow shows one of the texts of a slot of kind `text`;
  - `screen_reached`: a screen of the flow, after its start, is the screen of a slot of kind `screen`.
  Give each slot a name (lower case, underscores), its kind and a description general enough for any app ("the name of the place the forecast is for", "the title of the screen that confirms the account"). `reach` lists the numbers (1, 2, …) of the requirements the oracle decides: only those that the screens at the end of the flow show to be met.

# Slots

Fill every slot of the family you chose or described, from the screens below:
- a slot of kind `text`: one or more texts the LAST screens (those after the flow's last action) show, copied exactly, short (a few words), that show the outcome was reached. Do not take a text that the flow's FIRST screen also shows, nor buttons, tabs, menu entries or other texts that are always present: they would be shown whether or not the feature worked.
- a slot of kind `screen`: the key of a screen of the flow (`key=`), other than its first screen, that is only reached when the feature worked.

# The flow

{flow}

# Answer

Answer with JSON: `features`, a list with one entry per feature, each with `family` (an id of the catalogue, or "new"), `new_family` (null unless `family` is "new"), `slots` (one entry per slot: its name and its values; one value for a slot of kind `screen`), `name` (a short name of this app's feature), and `outcome` (what this app shows when the feature worked, in one sentence).
