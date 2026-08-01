# Tryton view schema coverage

This file records the implementation review against the Relax NG schemas in
`trytond/ir/ui`. It is kept beside the renderer so changes to Tryton's schemas
can be audited deliberately.

## Form

- Root: `on_write`, `creatable`, `col`, `cursor`, `scan_code`,
  `scan_code_depends` and `scan_code_states`.
- Structure: `label`, `field`, `image`, `separator`, `newline`, `button`,
  `link`, `notebook`/`page`, `group`, `hpaned` and `vpaned`.
- State and layout: `states`, `readonly`, `invisible`, `required`,
  `colspan`, `rowspan`, `xalign`, `yalign`, `xexpand`, `xfill`, `yexpand`,
  `yfill`, `width`, `height`, `help` and `help_field`.
- Field behaviour: `widget`, `factor`, `symbol`, `filename`,
  `filename_visible`, `completion`, `create`, `delete`, `view_ids`,
  `orientation`, `pre_validate`, `spell`, `mode`, `empty` and `toolbar`.
- Images and links: field/value images, URL images, colour swatches, sizes,
  action links and state evaluation.
- Buttons: class and instance methods, states, confirmation, icon, keyword,
  change metadata and multiple selection.

`scan_code_depends`, alignment/fill flags and x2many orientation are honoured
through the server record/context and responsive CSS rather than by copying
GTK layout behaviour literally.

Nested `col`/`colspan` grids, row spans, dimensions and alignment are
translated to CSS grid. Expandable groups remain native keyboard-accessible
`details` elements. Relation-created records carry an origin descriptor and
are linked back to the unfinished many2one, one2one or x2many value after save.

## Tree

- Root: `on_write`, `editable`, `creatable`, `sequence`, `keyword_open`,
  `tree_state` and `visual`.
- Fields: all tree widget names, `readonly`, `tree_invisible`, `optional`,
  `expand`, `visual`, `icon`, `sum`, dimensions, relation create/delete,
  orientation, pre-validation, completion, factor, filename, help field,
  view IDs, symbol and grouping.
- Prefix/suffix: value, text, Sao icon, URL image, colour and border metadata.
- Buttons: state, confirmation, type, keyword, visibility, width and multiple
  selection.

Hierarchical trees start collapsed, load descendants already returned by
Tryton progressively and persist expanded paths in the workspace. Optional
columns use the Sao hamburger icon. Sequence controls update both the visible
order and the sequence field; totals are rendered in a footer. Row and cell
`visual` expressions map to Sao's muted/success/warning/danger states.

## Calendar

`dtstart`, `dtend`, `mode`, `editable`, `color`, `background_color`, `width`
and `height` are parsed. Day, week and month navigation persist their current
date. Events may span dates, show configured fields and use validated dynamic
foreground/background colours. The user can switch the day/week/month mode;
blank days create a server-side draft and editable events can move between
days without being saved first.

## Widget families

The renderer has explicit implementations for:

- text: char, password, text, richtext, HTML, PYSON, email, URL, call and SIP;
- scalar: boolean, integer, float, numeric, timedelta and progress;
- temporal: date, time, datetime and timestamp;
- choice: selection and multiselection;
- relations: many2one, one2one, one2many, many2many and reference;
- payload: binary, image, document and dictionary.

Every editable control posts its value to the workspace even when no
`on_change` is declared. Relation completion calls the related model's
`autocomplete` method with its domain; open and create actions are available.

## Other schemas

`graph.rng` and `board.rng` were reviewed for shared field and structural
attributes. The requested Sao-compatible public view set is tree, form,
list-form and calendar, so graph and board are not advertised as selectable
views. Shared attributes used by board structures are implemented by the form
component renderer.
