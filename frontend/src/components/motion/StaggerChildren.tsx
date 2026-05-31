import React from 'react';
import { motion, type Variants } from 'motion/react';

/**
 * Editorial page-enter wrapper.
 * Children fade-up with stagger 60ms between siblings.
 * Each direct child should be wrapped in <StaggerItem> or use motion variants.
 */

const containerVariants: Variants = {
    hidden: { opacity: 1 },
    visible: {
        opacity: 1,
        transition: {
            staggerChildren: 0.06,
            delayChildren: 0.04,
        },
    },
};

const itemVariants: Variants = {
    hidden: { opacity: 0, y: 8 },
    visible: {
        opacity: 1,
        y: 0,
        transition: {
            duration: 0.48,
            ease: [0.16, 1, 0.3, 1],
        },
    },
};

export interface StaggerProps {
    children: React.ReactNode;
    className?: string;
    as?: 'div' | 'section' | 'main' | 'aside' | 'header' | 'ul';
}

export const StaggerChildren: React.FC<StaggerProps> = ({
    children,
    className,
    as = 'div',
}) => {
    const Tag = motion[as] as typeof motion.div;
    return (
        <Tag
            className={className}
            variants={containerVariants}
            initial="hidden"
            animate="visible"
        >
            {children}
        </Tag>
    );
};

export interface StaggerItemProps {
    children: React.ReactNode;
    className?: string;
    as?: 'div' | 'p' | 'h1' | 'h2' | 'h3' | 'span' | 'li' | 'header';
    style?: React.CSSProperties;
}

export const StaggerItem: React.FC<StaggerItemProps> = ({
    children,
    className,
    as = 'div',
    style,
}) => {
    const Tag = motion[as] as typeof motion.div;
    return (
        <Tag className={className} variants={itemVariants} style={style}>
            {children}
        </Tag>
    );
};
