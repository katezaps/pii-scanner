import "./PiiForm.css";

interface IdentityFields {
  email: string;
  phone: string;
  name: string;
  address: string;
}

interface PiiFormProps {
  identity: IdentityFields;
  onChange: (field: keyof IdentityFields, value: string) => void;
  onSubmit: () => void;
}

const fields: { key: keyof IdentityFields; label: string; type: string; placeholder: string }[] = [
  { key: "email", label: "Email", type: "email", placeholder: "you@example.com" },
  { key: "phone", label: "Phone", type: "tel", placeholder: "+1 (555) 123-4567" },
  { key: "name", label: "Full Name", type: "text", placeholder: "Jane Doe" },
  { key: "address", label: "Address", type: "text", placeholder: "123 Main St, City, ST 12345" },
];

export type { IdentityFields };

export default function PiiForm({ identity, onChange, onSubmit }: PiiFormProps) {
  return (
    <section className="pii-form panel">
      <h2 className="pii-form__title section-label">Your Information</h2>
      <p className="pii-form__hint">
        All fields are optional. Only provided fields will be checked.
      </p>
      <div
        className="pii-form__grid"
        onKeyDown={(e) => { if (e.key === "Enter") onSubmit(); }}
      >
        {fields.map((f) => (
          <div key={f.key} className="pii-form__field">
            <label className="pii-form__label" htmlFor={`pii-${f.key}`}>
              {f.label}
            </label>
            <input
              id={`pii-${f.key}`}
              className="pii-form__input input"
              type={f.type}
              placeholder={f.placeholder}
              value={identity[f.key]}
              onChange={(e) => onChange(f.key, e.target.value)}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
