
# {{project}} - Claude Context
**Generated:** {{generated_at}}

{% if active_session %}
## Active Task
**{{active_session.task}}** ({{active_session.developer}}, since {{active_session.started[:16]}})
{% endif %}

{% if latest_checkpoint %}
## Last Checkpoint
**{{latest_checkpoint.summary}}**
_{{latest_checkpoint.ts[:16]}} | {{latest_checkpoint.developer}}_
{% set steps = latest_checkpoint.next_steps %}
{% if steps %}
Next steps:
{% for s in steps %}- [ ] {{s}}
{% endfor %}{% endif %}
{% else %}
## Last Checkpoint
No checkpoints yet.
{% endif %}

{% if decisions %}
## Architectural Decisions
{% for d in decisions %}
**{{d.category}}:** {{d.decision}}
> {{d.question}}
{% endfor %}{% endif %}

{% if invariants %}
## Established Patterns
{% for i in invariants %}
- {{i.category}}: **{{i.pattern}}** (x{{i.count}})
{% endfor %}{% endif %}

{% if recent_actions %}
## Recent Actions
{% for a in recent_actions[:10] %}
- `{{a.tool}}` {{a.desc}} ({{a.ts[11:16]}})
{% endfor %}{% endif %}

{% if stalled %}
## Stalled Tasks
{% for s in stalled %}
- **{{s.task}}** (since {{s.started[:16]}})
{% endfor %}{% endif %}
