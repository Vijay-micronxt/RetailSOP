## Retail SOP

Multi-outlet food court SOP & compliance checklist system for ERPNext.

This app provides the backend (doctypes, validation, scheduler, and a
whitelisted REST API) for a checklist/compliance workflow. The frontend
(Lovable.dev) talks to this app exclusively through the whitelisted API
methods in `retail_sop/api.py` — this app does not ship a custom desk UI
beyond standard doctype forms needed for admin configuration.

### Installation

```bash
bench get-app retail_sop /path/to/retail_sop
bench --site your-site install-app retail_sop
```

### Key pieces

- **Doctypes**: Outlet, Checklist Template (+ Checklist Template Item),
  Shift Checklist (+ Shift Checklist Item), Checklist Deviation.
- **Scheduler**: `retail_sop.tasks.create_daily_shift_checklists` creates one
  Draft Shift Checklist per active Checklist Template every day.
- **API**: see `retail_sop/api.py` for the whitelisted methods consumed by
  the frontend.

#### License

mit
