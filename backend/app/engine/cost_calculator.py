class CostCalculator:
    """
    OpenCost-style cost allocation engine.
    Calculates cost based on the higher of requested vs actual usage to reflect reserved resource allocation.
    """
    
    @staticmethod
    def calculate_pod_cost(
        cpu_req: float,
        cpu_usage: float,
        mem_req_mb: float,
        mem_usage_mb: float,
        cpu_hourly_rate: float,
        ram_hourly_rate: float
    ) -> dict:
        """
        Calculates hourly cost and monthly estimate for a single pod.
        RAM hourly rate is per GB-hour.
        """
        # Allocate based on max of request vs usage (Kubernetes resource reservation model)
        effective_cpu = max(cpu_req, cpu_usage)
        effective_ram_gb = max(mem_req_mb, mem_usage_mb) / 1024.0
        
        cpu_cost_hr = effective_cpu * cpu_hourly_rate
        ram_cost_hr = effective_ram_gb * ram_hourly_rate
        
        total_hourly = cpu_cost_hr + ram_cost_hr
        total_monthly = total_hourly * 730.0 # 730 average hours per month
        
        # Resource efficiency percentage
        cpu_eff = (cpu_usage / cpu_req * 100.0) if cpu_req > 0 else 100.0
        mem_eff = (mem_usage_mb / mem_req_mb * 100.0) if mem_req_mb > 0 else 100.0
        overall_eff = min(100.0, max(0.0, (cpu_eff + mem_eff) / 2.0))
        
        # Determine visual color code for efficiency
        if overall_eff >= 65.0:
            status_color = "green"
        elif overall_eff >= 35.0:
            status_color = "yellow"
        else:
            status_color = "red"
            
        return {
            "hourly_cost": round(total_hourly, 4),
            "monthly_cost": round(total_monthly, 2),
            "efficiency_pct": round(overall_eff, 1),
            "status_color": status_color
        }
