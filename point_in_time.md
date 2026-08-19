# Point-in-time universe requirement

The current research universe is a starter list only. Before a production-grade backtest, MyStocks must ingest historical NSE constituent membership with effective dates.

A stock is eligible on date `t` only if it was actually eligible on `t`. Current constituents must never be projected backward through the entire five-year period.

The same rule applies to sectors, indices and peer groups: membership used by a historical observation must be known at that historical date.

Until this dataset is available, reports must label the universe as **research prototype / survivorship-bias risk**.
