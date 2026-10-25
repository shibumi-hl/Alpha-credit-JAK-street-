import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup); // без globals vitest Testing Library сама DOM между тестами не чистит
