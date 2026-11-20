You assess what processing of personal data a mobile application can be expected to need, from the context at the
end only. The context shows what the application was observed to do (the practices), the screens of the part of the
application where it happened, and documentation. It contains nothing the provider says about its own processing,
and you must not assume anything it would say.

The traffic shows, per practice, requests the application sent as they were captured: the method and URL, and an
excerpt of the field where the observation found the data, the data marked «». Where its content could not be read,
it says so. An endpoint's host and path can show what a transmission is for; cite traffic for an outcome only where
it shows that, not merely that data was sent.

For each practice listed in the context (its id starts with P):

1. State the purposes the practice plausibly serves, each as action, object, beneficiary (USER, PROVIDER or OTHER, for
   another party), context and outcome, with the node of the purpose vocabulary below that fits it best and its role
   (FUNCTIONAL if it serves something the user does on the screens, ANCILLARY otherwise). For the outcome, what the
   processing is for, give the ids of the screens and passages that show it. The practice itself shows only that the
   processing happens, not what it is for, so do not cite it for the outcome. Set "specific" to false if a purpose
   cannot be stated specifically.

2. For each purpose and each component of the practice (its data, and for a transmission its recipient; their ids
   are the practice's id followed by ".data" or ".recipient"), state the functional dependency of the purpose on the
   component:
   - ESSENTIAL: the purpose cannot be achieved without it;
   - QUALITY_DEPENDENT: achieved without it, less well;
   - NOT_DEPENDENT: the purpose is achieved as well without it;
   - NO_DEPENDENCY_IDENTIFIED: you cannot tell.
   Give your reasoning as numbered steps, each citing the context ids it rests on. That the application does
   something is never a reason that it needs to: a step may not cite a practice to show that the practice is needed.

Where no part of the context shows a part of a purpose or supports a step, cite "own knowledge" for it.

Nodes of the purpose vocabulary: {nodes}

Answer with JSON only, in the form the response schema gives, naming each practice by its id.

The context:

{context}
