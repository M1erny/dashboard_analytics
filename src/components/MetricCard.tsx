import React from 'react';
import { cn } from '../lib/utils';
import { ArrowUpRight, ArrowDownRight, Activity } from 'lucide-react';

interface MetricCardProps {
    title: string;
    value: string | number;
    subValue?: string;
    trend?: 'up' | 'down' | 'neutral';
    icon?: React.ReactNode;
    className?: string;
    description?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
    title,
    value,
    subValue,
    trend,
    icon,
    className,
    description
}) => {
    return (
        <div className={cn(
            "relative overflow-hidden rounded-xl border border-white/10 bg-white/5 p-6 backdrop-blur-lg transition-all hover:bg-white/10 hover:shadow-lg",
            className
        )}>
            <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
                {icon || <Activity className="h-4 w-4 text-muted-foreground" />}
            </div>
            <div className="mt-4 flex items-baseline gap-2">
                <span className="text-3xl font-bold tracking-tight text-white">{value}</span>
                {subValue && (
                    <span className={cn(
                        "flex items-center text-sm font-medium",
                        trend === 'up' ? "text-emerald-400" :
                            trend === 'down' ? "text-rose-400" : "text-muted-foreground"
                    )}>
                        {trend === 'up' && <ArrowUpRight className="mr-1 h-3 w-3" />}
                        {trend === 'down' && <ArrowDownRight className="mr-1 h-3 w-3" />}
                        {subValue}
                    </span>
                )}
            </div>
            {description && (
                <p className="mt-2 text-xs text-muted-foreground">{description}</p>
            )}

            {/* Decorative gradient blob */}
            <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-primary/10 blur-3xl transition-all group-hover:bg-primary/20" />
        </div>
    );
};
