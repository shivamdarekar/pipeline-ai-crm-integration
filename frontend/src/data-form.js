import { useState } from 'react';
import {
    Box,
    Button,
    Typography,
    Table,
    TableHead,
    TableBody,
    TableRow,
    TableCell,
    TableContainer,
    Paper,
    Chip,
    Divider,
    TextField,
    CircularProgress,
} from '@mui/material';
import axios from 'axios';

const endpointMapping = {
    'Notion': 'notion',
    'Airtable': 'airtable',
    'HubSpot': 'hubspot',
};

// ── HubSpot-specific table columns ──────────────────────────────
const HUBSPOT_COLUMNS = {
    Contact: [
        { label: 'Name',  key: 'name' },
        { label: 'ID',    key: 'id',   transform: v => v.replace('_Contact', '') },
        { label: 'Created', key: 'creation_time', transform: v => v ? new Date(v).toLocaleDateString() : '—' },
    ],
    Company: [
        { label: 'Name',  key: 'name' },
        { label: 'ID',    key: 'id',   transform: v => v.replace('_Company', '') },
        { label: 'Created', key: 'creation_time', transform: v => v ? new Date(v).toLocaleDateString() : '—' },
    ],
    Deal: [
        { label: 'Name',  key: 'name' },
        { label: 'ID',    key: 'id',   transform: v => v.replace('_Deal', '') },
        { label: 'Created', key: 'creation_time', transform: v => v ? new Date(v).toLocaleDateString() : '—' },
    ],
};

const HubSpotResults = ({ data }) => {
    const [showRaw, setShowRaw] = useState(false);

    const groups = ['Contact', 'Company', 'Deal'];
    const grouped = groups.reduce((acc, type) => {
        acc[type] = data.filter(item => item.type === type);
        return acc;
    }, {});

    return (
        <Box sx={{ mt: 3, width: '100%' }}>
            {/* Header + counts */}
            <Typography variant='h6' fontWeight={600} gutterBottom>
                HubSpot Data
            </Typography>
            <Divider sx={{ mb: 2 }} />
            <Box display='flex' gap={2} mb={3}>
                {groups.map(type => (
                    <Chip
                        key={type}
                        label={`${grouped[type].length} ${type}${grouped[type].length !== 1 ? 's' : ''}`}
                        color='primary'
                        variant='outlined'
                    />
                ))}
            </Box>

            {/* One table per type */}
            {groups.map(type => (
                grouped[type].length > 0 && (
                    <Box key={type} sx={{ mb: 3 }}>
                        <Typography variant='subtitle1' fontWeight={600} sx={{ mb: 1 }}>
                            {type}s ({grouped[type].length})
                        </Typography>
                        <TableContainer component={Paper} variant='outlined'>
                            <Table size='small'>
                                <TableHead>
                                    <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
                                        {HUBSPOT_COLUMNS[type].map(col => (
                                            <TableCell key={col.label} sx={{ fontWeight: 600 }}>
                                                {col.label}
                                            </TableCell>
                                        ))}
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {grouped[type].map((item, i) => (
                                        <TableRow key={i} hover>
                                            {HUBSPOT_COLUMNS[type].map(col => (
                                                <TableCell key={col.label}>
                                                    {col.transform ? col.transform(item[col.key]) : (item[col.key] || '—')}
                                                </TableCell>
                                            ))}
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    </Box>
                )
            ))}

            {/* Raw JSON toggle */}
            <Button
                size='small'
                variant='text'
                onClick={() => setShowRaw(p => !p)}
                sx={{ mt: 1 }}
            >
                {showRaw ? 'Hide Raw JSON' : 'Show Raw IntegrationItems'}
            </Button>
            {showRaw && (
                <TextField
                    value={JSON.stringify(data, null, 2)}
                    multiline
                    minRows={4}
                    maxRows={16}
                    disabled
                    fullWidth
                    sx={{ mt: 1, fontFamily: 'monospace' }}
                    InputLabelProps={{ shrink: true }}
                    label='Raw IntegrationItems'
                />
            )}
        </Box>
    );
};

// ── Generic JSON display for Airtable / Notion ───────────────────
const GenericResults = ({ data }) => (
    <TextField
        label='Loaded Data'
        value={typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
        sx={{ mt: 2 }}
        InputLabelProps={{ shrink: true }}
        multiline
        minRows={4}
        maxRows={16}
        disabled
        fullWidth
    />
);

// ── Main DataForm ────────────────────────────────────────────────
export const DataForm = ({ integrationType, credentials }) => {
    const [loadedData, setLoadedData] = useState(null);
    const [loading, setLoading] = useState(false);
    const endpoint = endpointMapping[integrationType];

    const handleLoad = async () => {
        try {
            setLoading(true);
            const formData = new FormData();
            formData.append('credentials', JSON.stringify(credentials));
            const response = await axios.post(
                `${process.env.REACT_APP_API_BASE_URL}/integrations/${endpoint}/load`,
                formData
            );
            setLoadedData(response.data);
        } catch (e) {
            alert(e?.response?.data?.detail);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Box display='flex' justifyContent='center' alignItems='center' flexDirection='column' width='100%'>
            <Box display='flex' flexDirection='column' width='100%'>
                <Button
                    onClick={handleLoad}
                    sx={{ mt: 2 }}
                    variant='contained'
                    disabled={loading}
                >
                    {loading ? <><CircularProgress size={18} sx={{ mr: 1 }} /> Loading...</> : 'Load Data'}
                </Button>

                {loadedData && (
                    <>
                        {integrationType === 'HubSpot'
                            ? <HubSpotResults data={loadedData} />
                            : <GenericResults data={loadedData} />
                        }
                        <Button
                            onClick={() => setLoadedData(null)}
                            sx={{ mt: 2 }}
                            variant='outlined'
                            color='error'
                            size='small'
                        >
                            Clear Data
                        </Button>
                    </>
                )}
            </Box>
        </Box>
    );
};
