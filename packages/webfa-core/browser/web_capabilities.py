from __future__ import annotations

from schemas.web import (
    CapabilityArgumentDescriptor,
    CapabilityDescriptor,
    ObjectCapabilityName,
)


_CAPABILITIES: dict[ObjectCapabilityName, CapabilityDescriptor] = {
    "open": CapabilityDescriptor(
        name="open",
        effect="navigation",
        description="Open the target represented by this WebObject in the current context.",
    ),
    "open_in_new_context": CapabilityDescriptor(
        name="open_in_new_context",
        effect="navigation",
        description="Open the target in a new browser context or tab when the BrowserHost supports it.",
    ),
    "activate": CapabilityDescriptor(
        name="activate",
        effect="unknown",
        description="Invoke the primary semantic behavior of the control.",
    ),
    "set_value": CapabilityDescriptor(
        name="set_value",
        effect="local_state_change",
        arguments={
            "value": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="The complete value to assign to the field.",
            )
        },
        description="Replace the current value of an editable field.",
    ),
    "clear_value": CapabilityDescriptor(
        name="clear_value",
        effect="local_state_change",
        description="Clear the current value of an editable field.",
    ),
    "choose": CapabilityDescriptor(
        name="choose",
        effect="local_state_change",
        arguments={
            "value": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="The option value or visible option text to choose.",
            )
        },
        description="Choose an option from a select-like object.",
    ),
    "toggle": CapabilityDescriptor(
        name="toggle",
        effect="local_state_change",
        arguments={
            "checked": CapabilityArgumentDescriptor(
                type="boolean",
                required=False,
                description="Optional desired checked state. Omit to invert the current state.",
            )
        },
        description="Toggle a checkbox, radio, switch, or equivalent object.",
    ),
    "submit": CapabilityDescriptor(
        name="submit",
        effect="external_write",
        requires_confirmation=True,
        description="Submit a form. P11 applies the final authority and confirmation policy.",
    ),
    "expand": CapabilityDescriptor(
        name="expand",
        effect="local_state_change",
        description="Expand a currently collapsed object.",
    ),
    "collapse": CapabilityDescriptor(
        name="collapse",
        effect="local_state_change",
        description="Collapse a currently expanded object.",
    ),
    "dismiss": CapabilityDescriptor(
        name="dismiss",
        effect="local_state_change",
        description="Dismiss a dialog, alert, or dismissible surface.",
    ),
    "download": CapabilityDescriptor(
        name="download",
        effect="download",
        description="Download the resource through the future WebFA resource bridge.",
    ),
    "upload": CapabilityDescriptor(
        name="upload",
        effect="upload",
        requires_confirmation=True,
        arguments={
            "resource_ref": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="A WebFA-approved local resource reference, never an arbitrary local path.",
            ),
            "purpose": CapabilityArgumentDescriptor(
                type="string",
                required=False,
                description="Optional task purpose; when provided it must match the resource grant.",
            ),
        },
        description="Upload a scoped WebFA-approved resource through the local resource broker.",
    ),
    "provide_payment_instrument": CapabilityDescriptor(
        name="provide_payment_instrument",
        effect="external_write",
        requires_confirmation=True,
        arguments={
            "instrument_id": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="Opaque WebFA payment instrument reference. Payment secrets are never Agent-visible.",
            ),
            "amount": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="Expected transaction amount as a decimal string.",
            ),
            "currency": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="Three-letter transaction currency code.",
            ),
            "transaction_kind": CapabilityArgumentDescriptor(
                type="string",
                required=True,
                description="Financial transaction kind declared in the SafetyContext.",
            ),
            "recurring": CapabilityArgumentDescriptor(
                type="boolean",
                required=False,
                description="Whether the transaction creates a recurring commitment.",
            ),
        },
        description="Use an opaque payment instrument through the protected Payment Instrument Broker.",
    ),
    "request_human_takeover": CapabilityDescriptor(
        name="request_human_takeover",
        effect="unknown",
        description="Request the WebFA human takeover surface for an operation that cannot be safely completed by the agent.",
    ),
}


def capability_descriptor(name: ObjectCapabilityName) -> CapabilityDescriptor:
    return _CAPABILITIES[name].model_copy(deep=True)


def capability_descriptors() -> dict[ObjectCapabilityName, CapabilityDescriptor]:
    return {name: descriptor.model_copy(deep=True) for name, descriptor in _CAPABILITIES.items()}
