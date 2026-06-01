"""Diagnostic chart helpers for module-level QA PNG and HTML dashboard outputs."""

from diagnostics.module_charts import (
    write_module1_charts,
    write_module2_charts,
    write_module3_charts,
    write_module4_charts,
    write_module6_charts,
    write_module7_charts,
    write_workflow_summary_charts,
)
from diagnostics.plotly_dashboard import (
    write_module_pages,
    module1_figures,
    module2_figures,
    module3_figures,
    module4_figures,
    module5_figures,
    module6_figures,
    module7_figures,
    workflow_summary_figures,
)

__all__ = [
    # matplotlib PNG writers
    "write_module1_charts",
    "write_module2_charts",
    "write_module3_charts",
    "write_module4_charts",
    "write_module6_charts",
    "write_module7_charts",
    "write_workflow_summary_charts",
    # Plotly HTML dashboard
    "write_module_pages",
    "module1_figures",
    "module2_figures",
    "module3_figures",
    "module4_figures",
    "module5_figures",
    "module6_figures",
    "module7_figures",
    "workflow_summary_figures",
]
