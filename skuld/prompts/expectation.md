You assess what processing of personal data a mobile application can be expected to need, from the context below
only. The context shows what the application was observed to do (the practices), the screens of the part of the
application where it happened, and documentation. It contains nothing the provider says about its own processing,
and you must not assume anything it would say.

{context}

For each practice listed in the context (its id starts with P):

1. State the purposes the practice plausibly serves, each as action, object, beneficiary (USER, PROVIDER or OTHER, for
   another party), context and outcome, with the node of the purpose vocabulary below that fits it best and its role
   (FUNCTIONAL if it serves something the user does on the screens, ANCILLARY otherwise). For the outcome, what the
   processing is for, give the ids of the screens and passages that show it. The practice itself shows only that the
   processing happens, not what it is for, so do not cite it for the outcome. Set "specific" to false if a purpose
   cannot be stated specifically.

2. For each purpose and each component of the practice (its data, and for a transmission its recipient; their ids
   are the practice's id followed by ".data" or ".recipient"), propose the less invasive alternatives that would still
   achieve the purpose: a change of the component (less data, coarser data, an identifier of narrower scope,
   processing on the device, no recipient or a recipient of narrower reach). Give each an evidence level, PLAUSIBLE
   (coherent, not substantiated by the context) or TECHNICALLY_SUPPORTED (a cited document describes the mechanism by
   which the purpose is achieved with the alternative), and the ids of the context parts it rests on. That the
   application does something is never a reason that it needs to. Leave out alternatives that would not achieve the
   purpose, and give none where you can state none.

Where no part of the context shows a purpose's outcome or supports an alternative, cite "own knowledge" for it.

Nodes of the purpose vocabulary: {nodes}

Answer with JSON only, in the form the response schema gives, naming each practice by its id.
