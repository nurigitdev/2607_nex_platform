import { LoaderCircle } from "lucide-react";
import {
  forwardRef,
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { classNames } from "./classNames";
import styles from "./components.module.css";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ControlSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: ButtonVariant;
  readonly size?: ControlSize;
  readonly loading?: boolean;
  readonly leadingIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    leadingIcon,
    className,
    children,
    disabled,
    type = "button",
    ...props
  },
  ref,
) {
  return (
    <button
      {...props}
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classNames(
        styles.button,
        styles[`button_${variant}`],
        styles[`control_${size}`],
        className,
      )}
    >
      {loading ? (
        <LoaderCircle aria-hidden="true" className={styles.spin} size={18} />
      ) : (
        leadingIcon
      )}
      <span>{children}</span>
    </button>
  );
});

export interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children"> {
  readonly label: string;
  readonly icon: ReactNode;
  readonly variant?: ButtonVariant;
  readonly size?: ControlSize;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    {
      label,
      icon,
      variant = "ghost",
      size = "md",
      className,
      type = "button",
      ...props
    },
    ref,
  ) {
    if (!label.trim()) throw new Error("IconButton requires an accessible label");
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        aria-label={label}
        className={classNames(
          styles.button,
          styles.iconButton,
          styles[`button_${variant}`],
          styles[`control_${size}`],
          className,
        )}
      >
        {icon}
      </button>
    );
  },
);

interface FieldFrameProps {
  readonly id?: string;
  readonly label: string;
  readonly hint?: string;
  readonly error?: string;
  readonly required?: boolean;
  readonly children: (ids: {
    id: string;
    describedBy?: string;
    invalid: boolean;
  }) => ReactNode;
}

function FieldFrame({
  id: providedId,
  label,
  hint,
  error,
  required,
  children,
}: FieldFrameProps) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  const descriptionId = hint || error ? `${id}-description` : undefined;
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {children({ id, describedBy: descriptionId, invalid: Boolean(error) })}
      {hint || error ? (
        <p
          id={descriptionId}
          className={classNames(styles.fieldMessage, error && styles.fieldError)}
        >
          {error ?? hint}
        </p>
      ) : null}
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  readonly label: string;
  readonly hint?: string;
  readonly error?: string;
  readonly controlSize?: Exclude<ControlSize, "sm">;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    hint,
    error,
    controlSize = "md",
    id,
    required,
    className,
    ...props
  },
  ref,
) {
  return (
    <FieldFrame {...{ id, label, hint, error, required }}>
      {({ id: fieldId, describedBy, invalid }) => (
        <input
          {...props}
          ref={ref}
          id={fieldId}
          required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={classNames(
            styles.input,
            styles[`control_${controlSize}`],
            invalid && styles.inputInvalid,
            className,
          )}
        />
      )}
    </FieldFrame>
  );
});

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  readonly label: string;
  readonly hint?: string;
  readonly error?: string;
  readonly controlSize?: Exclude<ControlSize, "sm">;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    label,
    hint,
    error,
    controlSize = "md",
    id,
    required,
    className,
    children,
    ...props
  },
  ref,
) {
  return (
    <FieldFrame {...{ id, label, hint, error, required }}>
      {({ id: fieldId, describedBy, invalid }) => (
        <select
          {...props}
          ref={ref}
          id={fieldId}
          required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={classNames(
            styles.input,
            styles[`control_${controlSize}`],
            invalid && styles.inputInvalid,
            className,
          )}
        >
          {children}
        </select>
      )}
    </FieldFrame>
  );
});

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  readonly label: string;
  readonly hint?: string;
  readonly error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    { label, hint, error, id, required, className, ...props },
    ref,
  ) {
    return (
      <FieldFrame {...{ id, label, hint, error, required }}>
        {({ id: fieldId, describedBy, invalid }) => (
          <textarea
            {...props}
            ref={ref}
            id={fieldId}
            required={required}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className={classNames(
              styles.input,
              styles.textarea,
              invalid && styles.inputInvalid,
              className,
            )}
          />
        )}
      </FieldFrame>
    );
  },
);

interface ChoiceProps extends InputHTMLAttributes<HTMLInputElement> {
  readonly label: string;
}

function Choice({ label, className, ...props }: ChoiceProps) {
  return (
    <label className={classNames(styles.choice, className)}>
      <input {...props} className={styles.choiceInput} />
      <span>{label}</span>
    </label>
  );
}

export function Checkbox(props: Omit<ChoiceProps, "type">) {
  return <Choice {...props} type="checkbox" />;
}

export function Radio(props: Omit<ChoiceProps, "type">) {
  return <Choice {...props} type="radio" />;
}
